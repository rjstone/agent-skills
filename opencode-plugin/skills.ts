// Pure logic for the agent-skills opencode plugin: pick skills by set and read
// them from skills/<name>/SKILL.md. Node built-ins only, erasable TypeScript
// only, so Node (>= 22.18) and opencode both run it as is.
import { readFile } from "node:fs/promises"
import { join, resolve } from "node:path"

export type SkillEntry = {
  id: string
  name: string
  description: string
  /** Absolute path of the real SKILL.md, so relative scripts/ and references/ resolve. */
  path: string
  /** SKILL.md body after the frontmatter. */
  content: string
}

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/

function unquote(value: string): string {
  const v = value.trim()
  if (v.length >= 2 && (v[0] === '"' || v[0] === "'") && v[v.length - 1] === v[0]) return v.slice(1, -1)
  return v
}

export function parseFrontmatter(text: string): { name?: string; description?: string; body: string } {
  const m = FRONTMATTER.exec(text)
  if (!m) return { body: text }
  const out: { name?: string; description?: string; body: string } = { body: text.slice(m[0].length) }
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^(name|description):\s*(.*)$/.exec(line)
    if (kv) out[kv[1] as "name" | "description"] = unquote(kv[2])
  }
  return out
}

export function resolveSets(option: unknown, sets: Record<string, string[]>): string[] {
  const chosen = option === undefined || option === null ? [] : typeof option === "string" ? [option] : option
  if (!Array.isArray(chosen)) throw new Error('the "sets" option must be a set name or a list of set names')
  const out: string[] = []
  for (const name of chosen) {
    const skills = typeof name === "string" ? sets[name] : undefined
    if (!skills) {
      throw new Error(`unknown skill set "${String(name)}"; known sets: ${Object.keys(sets).join(", ")}`)
    }
    for (const skill of skills) if (!out.includes(skill)) out.push(skill)
  }
  return out
}

export async function loadSkills(root: string, names: string[]): Promise<SkillEntry[]> {
  const out: SkillEntry[] = []
  for (const name of names) {
    const path = resolve(join(root, "skills", name, "SKILL.md"))
    const fm = parseFrontmatter(await readFile(path, "utf8"))
    if (!fm.name || !fm.description) throw new Error(`${path}: frontmatter needs "name" and "description"`)
    out.push({ id: fm.name, name: fm.name, description: fm.description, path, content: fm.body })
  }
  return out
}

export function planAdds(existing: Set<string>, entries: SkillEntry[]): { add: SkillEntry[]; skipped: string[] } {
  const add: SkillEntry[] = []
  const skipped: string[] = []
  for (const e of entries) (existing.has(e.id) ? skipped.push(e.id) : add.push(e))
  return { add, skipped }
}
