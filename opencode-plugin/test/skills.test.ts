// Unit tests for opencode-plugin/skills.ts. Run: node --test opencode-plugin/test/
import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { isAbsolute, join } from "node:path"
import { loadSkills, parseFrontmatter, planAdds, resolveSets } from "../skills.ts"
import type { SkillEntry } from "../skills.ts"

function fixture(): string {
  const root = mkdtempSync(join(tmpdir(), "skillsets-"))
  mkdirSync(join(root, "skills", "a"), { recursive: true })
  mkdirSync(join(root, "skills", "b"), { recursive: true })
  writeFileSync(join(root, "skills", "a", "SKILL.md"), "---\nname: a\ndescription: Use when a.\n---\n# a\n")
  writeFileSync(
    join(root, "skills", "b", "SKILL.md"),
    '---\r\nname: b\r\ndescription: "Use when b: quoted."\r\nlicense: MIT\r\n---\r\n# b\r\n',
  )
  return root
}

test("parseFrontmatter handles CRLF and quotes", () => {
  const got = parseFrontmatter('---\r\nname: b\r\ndescription: "Use when b: quoted."\r\n---\r\n# b\r\n')
  assert.equal(got.name, "b")
  assert.equal(got.description, "Use when b: quoted.")
  assert.ok(got.body.startsWith("# b"))
})

test("resolveSets: string means one set", () => {
  assert.deepEqual(resolveSets("ab", { ab: ["a", "b"] }), ["a", "b"])
})

test("resolveSets: dedupes across sets", () => {
  assert.deepEqual(resolveSets(["ab", "bc"], { ab: ["a", "b"], bc: ["b", "c"] }), ["a", "b", "c"])
})

test("resolveSets: unknown set lists known sets", () => {
  assert.throws(() => resolveSets(["zz"], { ab: ["a"], bc: ["b"] }), /unknown skill set "zz"; known sets: ab, bc/)
})

test("resolveSets: no option loads nothing", () => {
  assert.deepEqual(resolveSets(undefined, { ab: ["a"] }), [])
  assert.deepEqual(resolveSets([], { ab: ["a"] }), [])
})

test("loadSkills reads real path and body", async () => {
  const root = fixture()
  try {
    const [a, b] = await loadSkills(root, ["a", "b"])
    assert.equal(a.id, "a")
    assert.equal(a.description, "Use when a.")
    assert.ok(isAbsolute(a.path))
    assert.ok(a.path.replaceAll("\\", "/").endsWith("skills/a/SKILL.md"))
    assert.equal(a.content, "# a\n")
    assert.equal(b.description, "Use when b: quoted.")
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test("loadSkills names the file when frontmatter is incomplete", async () => {
  const root = fixture()
  try {
    writeFileSync(join(root, "skills", "a", "SKILL.md"), "---\nname: a\n---\nbody\n")
    await assert.rejects(loadSkills(root, ["a"]), /skills[\\/]a[\\/]SKILL\.md/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test("planAdds skips existing ids", () => {
  const entry = (id: string): SkillEntry => ({ id, name: id, description: "d", path: "/x", content: "" })
  const got = planAdds(new Set(["a"]), [entry("a"), entry("b")])
  assert.deepEqual(got.add.map((e) => e.id), ["b"])
  assert.deepEqual(got.skipped, ["a"])
})
