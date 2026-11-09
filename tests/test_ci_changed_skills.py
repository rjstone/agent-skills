"""Tests for scripts/ci_changed_skills.py (which skills CI must test).

Pure classification plus a throwaway git repo for the version check.
Run from the repo root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "ci_changed_skills.py")
spec = importlib.util.spec_from_file_location("ccs", SCRIPT)
ccs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccs)

SKILLS = {"alpha", "beta-tool"}


class TestClassify(unittest.TestCase):
    def test_skill_files_select_that_skill(self):
        self.assertEqual(ccs.classify(["skills/alpha/SKILL.md", "skills/alpha/scripts/x.py"], SKILLS),
                         ({"alpha"}, {"alpha"}))

    def test_skill_test_file_selects_skill_but_needs_no_bump(self):
        self.assertEqual(ccs.classify(["tests/test_beta_tool.py"], SKILLS), ({"beta-tool"}, set()))

    def test_shared_files_select_all(self):
        for p in ("tests/test_skills.py", "tests/test_public_safety.py", "tests/_helpers.py",
                  ".github/workflows/ci.yml", "scripts/ci_changed_skills.py"):
            self.assertEqual(ccs.classify([p], SKILLS)[0], ccs.ALL, p)

    def test_notes_select_nothing(self):
        self.assertEqual(ccs.classify(["AGENTS.md", "TODO.md", "docs/plans/x.md"], SKILLS), (set(), set()))

    def test_deleted_skill_is_not_tested(self):
        # a removed skill no longer exists in the tree: nothing to test
        self.assertEqual(ccs.classify(["skills/gone/SKILL.md"], SKILLS), (set(), set()))

    def test_version_key(self):
        self.assertLess(ccs.version_key('"0.1.0"'), ccs.version_key('"0.1.1"'))
        self.assertLess(ccs.version_key('"0.9.0"'), ccs.version_key('"0.10.0"'))
        self.assertIsNone(ccs.version_key("nope"))


class TestVersionCheck(unittest.TestCase):
    """A real git repo: base commit, then a change on top."""

    def git(self, *args):
        return subprocess.run(["git", "-C", self.dir, *args], check=True, capture_output=True, text=True).stdout.strip()

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def skill(self, name, version, body="Body.\n"):
        self.write(f"skills/{name}/SKILL.md",
                   f'---\nname: {name}\ndescription: Use when testing.\nlicense: MIT\nmetadata:\n'
                   f'  author: Someone\n  source: https://example.com\n  version: "{version}"\n---\n{body}')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.skill("alpha", "0.1.0")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "change")

    def test_edit_without_bump_fails(self):
        self.skill("alpha", "0.1.0", body="Changed.\n")
        self.commit()
        problems = ccs.check_versions(self.dir, self.base, {"alpha"})
        self.assertEqual(len(problems), 1)
        self.assertIn("alpha", problems[0])

    def test_edit_with_bump_passes(self):
        self.skill("alpha", "0.1.1", body="Changed.\n")
        self.commit()
        self.assertEqual(ccs.check_versions(self.dir, self.base, {"alpha"}), [])

    def test_lower_version_fails(self):
        self.skill("alpha", "0.0.9", body="Changed.\n")
        self.commit()
        self.assertTrue(ccs.check_versions(self.dir, self.base, {"alpha"}))

    def test_new_skill_needs_no_bump(self):
        self.skill("beta", "0.1.0")
        self.commit()
        self.assertEqual(ccs.check_versions(self.dir, self.base, {"beta"}), [])

    def test_changed_files_from_git(self):
        self.skill("alpha", "0.1.1", body="Changed.\n")
        self.write("TODO.md", "x\n")
        self.commit()
        self.assertEqual(sorted(ccs.changed_files(self.dir, self.base)), ["TODO.md", "skills/alpha/SKILL.md"])


if __name__ == "__main__":
    unittest.main()
