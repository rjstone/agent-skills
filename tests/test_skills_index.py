"""Tests for scripts/build_skills_index.py (skills/index.json, the opencode
HTTP skill catalog served from raw.githubusercontent.com).

Run from the repo root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "build_skills_index.py")
spec = importlib.util.spec_from_file_location("bsi", SCRIPT)
bsi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsi)


def skill_md(name, version):
    return (f'---\nname: {name}\ndescription: Use when testing.\nlicense: MIT\nmetadata:\n'
            f'  author: Someone\n  source: https://example.com\n  version: "{version}"\n---\nBody\n')


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.skills = os.path.join(self.root, "skills")
        self.write("beta/SKILL.md", skill_md("beta", "0.2.0"))
        self.write("beta/references/b.md", "b\n")
        self.write("beta/scripts/__pycache__/x.cpython-313.pyc", "junk")
        self.write("alpha/SKILL.md", skill_md("alpha", "0.1.0"))
        self.write("not-a-skill/README.md", "no SKILL.md here\n")

    def write(self, rel, text):
        path = os.path.join(self.skills, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = bsi.main([*argv, "--skills-dir", self.skills])
        return code, out.getvalue()

    def test_build_lists_skills_sorted_with_versions_and_files(self):
        index = bsi.build_index(self.skills)
        self.assertEqual(index, {"skills": [
            {"name": "alpha", "version": "0.1.0", "files": ["SKILL.md"]},
            {"name": "beta", "version": "0.2.0", "files": ["SKILL.md", "references/b.md"]},
        ]})

    def test_render_is_stable_lf_json_with_trailing_newline(self):
        text = bsi.render(bsi.build_index(self.skills))
        self.assertTrue(text.endswith("}\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(json.loads(text), bsi.build_index(self.skills))
        self.assertEqual(text, bsi.render(bsi.build_index(self.skills)))

    def test_root_index_json_is_not_an_entry_but_a_skill_file_of_that_name_is(self):
        self.run_main()  # writes skills/index.json at the root
        self.write("alpha/index.json", "{}")  # a skill's own file with that name
        index = bsi.build_index(self.skills)
        self.assertEqual([e["name"] for e in index["skills"]], ["alpha", "beta"])
        files = {e["name"]: e["files"] for e in index["skills"]}
        self.assertIn("index.json", files["alpha"])
        self.assertNotIn("index.json", files["beta"])

    def test_write_then_check(self):
        code, _ = self.run_main("--check")
        self.assertEqual(code, 1)  # missing
        self.assertEqual(self.run_main()[0], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.skills, "index.json")))
        self.assertEqual(self.run_main("--check")[0], 0)
        self.write("alpha/SKILL.md", skill_md("alpha", "0.1.1"))
        code, out = self.run_main("--check")
        self.assertEqual(code, 1)  # stale after a version bump
        self.assertIn("stale", out)

    def test_missing_version_fails(self):
        self.write("gamma/SKILL.md", "---\nname: gamma\ndescription: Use when x.\n---\nBody\n")
        with self.assertRaises(SystemExit):
            bsi.build_index(self.skills)


class TestRepoIndex(unittest.TestCase):
    def test_every_repo_skill_has_a_version_the_index_can_read(self):
        index = bsi.build_index(os.path.join(REPO_ROOT, "skills"))
        names = sorted(d for d in os.listdir(os.path.join(REPO_ROOT, "skills"))
                       if os.path.isfile(os.path.join(REPO_ROOT, "skills", d, "SKILL.md")))
        self.assertEqual([e["name"] for e in index["skills"]], names)


if __name__ == "__main__":
    unittest.main()
