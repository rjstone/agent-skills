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
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)


def skill_dirs():
    return sorted(d for d in os.listdir(SKILLS)
                  if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md")))


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def frontmatter(text):
    m = FRONTMATTER.match(text)
    if not m:
        return None
    fields = {}
    for line in m.group(1).split("\n"):
        k, sep, v = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[k.strip()] = v.strip()
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
