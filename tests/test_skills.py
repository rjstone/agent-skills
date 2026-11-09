"""Checks every skills/<name>/SKILL.md against the format skills.sh (npx skills)
and the agentskills.io spec expect, plus this repo's own rules (AGENTS.md).

Run from the repo root: python3 -m unittest discover -s tests -v
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(REPO_ROOT, "skills")
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Frontmatter standard (AGENTS.md "Skill frontmatter", the user, 2026-11-08)
ORDER = ["name", "description", "compatibility", "license", "metadata"]
REQUIRED = {"name", "description", "license", "metadata"}
SOURCE = "https://github.com/rjstone/agent-skills"
VERSION = re.compile(r'^"\d+\.\d+\.\d+"$')
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def skill_dirs():
    return sorted(d for d in os.listdir(SKILLS)
                  if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def frontmatter(text):
    """Top-level keys (in order) -> raw value; metadata's indented keys go in
    fields["_metadata"]. Enough for this repo's flat frontmatter."""
    m = FRONTMATTER.match(text)
    if not m:
        return None
    fields, meta, keys = {}, {}, []
    for line in m.group(1).split("\n"):
        k, sep, v = line.partition(":")
        if not sep:
            continue
        if line.startswith(("  ", "\t")):
            meta[k.strip()] = v.strip()
        else:
            keys.append(k.strip())
            fields[k.strip()] = v.strip()
    fields["_order"], fields["_metadata"] = keys, meta
    return fields


class TestSkills(unittest.TestCase):
    def test_there_are_skills(self):
        self.assertTrue(skill_dirs())

    def test_every_skill_dir_has_skill_md(self):
        for d in os.listdir(SKILLS):
            if os.path.isdir(os.path.join(SKILLS, d)):
                self.assertTrue(os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")), d)

    def test_frontmatter(self):
        for d in skill_dirs():
            with self.subTest(skill=d):
                fm = frontmatter(read(os.path.join(SKILLS, d, "SKILL.md")))
                self.assertIsNotNone(fm, "no --- frontmatter --- block at the top")
                self.assertEqual(fm.get("name"), d, "name must equal the folder name")
                self.assertRegex(fm["name"], NAME, "lowercase letters, digits, hyphens")
                desc = fm.get("description", "")
                self.assertNotIn(desc, ("", ">", "|", ">-", "|-"), "single-line description")
                self.assertTrue(desc.startswith("Use when"), "description starts with 'Use when'")
                self.assertLessEqual(len(desc), 1024)

    def test_frontmatter_standard(self):
        for d in skill_dirs():
            with self.subTest(skill=d):
                fm = frontmatter(read(os.path.join(SKILLS, d, "SKILL.md")))
                keys = fm["_order"]
                self.assertTrue(REQUIRED <= set(keys), f"missing {REQUIRED - set(keys)}")
                self.assertTrue(set(keys) <= set(ORDER), f"unknown keys {set(keys) - set(ORDER)}")
                self.assertEqual(keys, [k for k in ORDER if k in keys], "keys out of order")
                self.assertEqual(fm["license"], "MIT")
                meta = fm["_metadata"]
                self.assertTrue(meta.get("author", "").startswith("Robert Stone"), "metadata.author")
                self.assertEqual(meta.get("source"), SOURCE, "metadata.source")
                self.assertRegex(meta.get("version", ""), VERSION, 'metadata.version as a quoted "X.Y.Z"')
                if "compatibility" in fm:
                    self.assertTrue(1 <= len(fm["compatibility"]) <= 500, "compatibility 1-500 chars")

    def test_references_are_linked_from_skill_md(self):
        for d in skill_dirs():
            refs = os.path.join(SKILLS, d, "references")
            if not os.path.isdir(refs):
                continue
            text = read(os.path.join(SKILLS, d, "SKILL.md"))
            for name in sorted(os.listdir(refs)):
                if name.endswith(".md"):
                    with self.subTest(skill=d, ref=name):
                        self.assertIn(f"references/{name}", text)

    def test_no_nested_skill_md(self):
        # a SKILL.md below a skill would be discovered as a second skill
        for d in skill_dirs():
            for root, _, files in os.walk(os.path.join(SKILLS, d)):
                if root != os.path.join(SKILLS, d):
                    self.assertNotIn("SKILL.md", files, root)


if __name__ == "__main__":
    unittest.main()
