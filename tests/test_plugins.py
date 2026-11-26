"""Tests for scripts/build_plugins.py: skill-sets.json -> the local Claude
marketplace (.claude-plugin/marketplace.json) and opencode-plugin/sets.json.

Shared test (runs for every change). Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "build_plugins.py")
spec = importlib.util.spec_from_file_location("bp", SCRIPT)
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)

FIRST_SETS = [
    ("opencode-dev", ["opencode-build", "opencode-cli", "opencode-api", "opencode-console"]),
    ("docshelf", ["docshelf", "docshelf-build"]),
    ("special-agents", ["provider-onboarding", "decisions"]),
]


def config(sets):
    return {"marketplace": {"name": "agent-skills", "owner": {"name": "Robert Stone"},
                            "description": "d"},
            "sets": sets}


class TestBuildPlugins(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        for name in "abc":
            path = os.path.join(self.root, "skills", name, "SKILL.md")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"---\nname: {name}\ndescription: Use when testing.\n---\nBody\n")
        self.skills = os.path.join(self.root, "skills")

    def write_sets(self, obj_or_text):
        text = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text)
        with open(os.path.join(self.root, "skill-sets.json"), "w", encoding="utf-8") as f:
            f.write(text)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bp.main([*argv, "--root", self.root])
        return code, out.getvalue(), err.getvalue()

    def test_marketplace_lists_only_set_skills_from_skills_root(self):
        cfg = config([{"name": "ab", "description": "A and B", "skills": ["a", "b"]}])
        self.assertEqual(bp.build_marketplace(cfg), {
            "name": "agent-skills", "owner": {"name": "Robert Stone"},
            "metadata": {"description": "d"},
            "plugins": [{"name": "ab", "description": "A and B",
                         "source": "./skills", "skills": ["./a", "./b"]}]})

    def test_opencode_sets_map(self):
        cfg = config([{"name": "ab", "description": "x", "skills": ["a", "b"]},
                      {"name": "c-only", "description": "y", "skills": ["c"]}])
        self.assertEqual(bp.build_opencode_sets(cfg), {"ab": ["a", "b"], "c-only": ["c"]})

    def test_missing_skill_is_error_naming_set_and_skill(self):
        self.write_sets(config([{"name": "ab", "description": "x", "skills": ["a", "zzz"]}]))
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("ab", err)
        self.assertIn("zzz", err)

    def test_invalid_configs_exit_2_with_one_line(self):
        good = {"name": "ab", "description": "x", "skills": ["a"]}
        cases = {
            "bad json": "{not json",
            "no sets": {"marketplace": config([])["marketplace"]},
            "no marketplace": {"sets": [good]},
            "duplicate": config([good, dict(good)]),
            "bad name": config([dict(good, name="Bad_Name")]),
            "empty description": config([dict(good, description="  ")]),
            "no skills": config([dict(good, skills=[])]),
            "skills not list": config([dict(good, skills="a")]),
        }
        for label, value in cases.items():
            with self.subTest(label):
                self.write_sets(value)
                code, _, err = self.run_main()
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("error:"), err)
                self.assertEqual(err.strip().count("\n"), 0, err)
                self.assertNotIn("Traceback", err)

    def test_missing_sets_file_exit_2(self):
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("skill-sets.json", err)

    def test_set_may_share_name_with_skill(self):
        self.assertEqual(bp.validate(config([{"name": "a", "description": "x", "skills": ["a"]}]),
                                     self.skills), [])

    def test_skill_in_two_sets_warns(self):
        cfg = config([{"name": "ab", "description": "x", "skills": ["a", "b"]},
                      {"name": "bc", "description": "y", "skills": ["b", "c"]}])
        warnings = bp.validate(cfg, self.skills)
        self.assertEqual(len(warnings), 1)
        self.assertIn('"b"', warnings[0])

    def test_check_reports_stale_then_clean(self):
        self.write_sets(config([{"name": "ab", "description": "x", "skills": ["a", "b"]}]))
        self.assertEqual(self.run_main("--check")[0], 1)
        self.assertEqual(self.run_main()[0], 0)
        self.assertEqual(self.run_main("--check")[0], 0)
        self.write_sets(config([{"name": "ab", "description": "x", "skills": ["a"]}]))
        code, out, _ = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("marketplace.json", out)

    def test_render_lf_trailing_newline(self):
        text = bp.render({"a": [1]})
        self.assertTrue(text.endswith("}\n"))
        self.assertNotIn("\r", text)
        self.assertIn('\n  "a"', text)

    def test_repo_outputs_are_current(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(bp.main(["--check"]), 0)

    def test_repo_first_sets_are_exact(self):
        with open(os.path.join(REPO_ROOT, "skill-sets.json"), encoding="utf-8") as f:
            sets = json.load(f)["sets"]
        self.assertEqual([(s["name"], s["skills"]) for s in sets], FIRST_SETS)


if __name__ == "__main__":
    unittest.main()
