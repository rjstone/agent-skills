"""Tests for scripts/skillspector_ci.py. Pure: SARIF reports are fixtures and
subprocess.run is mocked, so no scanner or network is needed. Run from the
repo root: python3 -m unittest discover -s tests -v
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "skillspector_ci", os.path.join(REPO_ROOT, "scripts", "skillspector_ci.py"))
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def result(rule, sev, uri, line=1, suppressed=False):
    r = {"ruleId": rule, "level": "error" if sev in ("HIGH", "CRITICAL") else "warning",
         "message": {"text": f"{rule} text"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                             "region": {"startLine": line}}}],
         "properties": {"severity": sev}}
    if suppressed:
        r["suppressions"] = [{"kind": "external", "justification": "accepted"}]
    return r


def sarif(results, rules=("A1",), ok=True, complete=True, pct=100.0):
    return {"$schema": "x", "version": "2.1.0", "runs": [{
        "tool": {"driver": {"name": "skillspector", "version": "9.9.9",
                            "rules": [{"id": r} for r in rules]}},
        "results": results,
        "invocations": [{
            "executionSuccessful": ok,
            "toolExecutionNotifications": [{"message": {"text": "n"}, "locations": [
                {"physicalLocation": {"artifactLocation": {"uri": "SKILL.md"}}}]}],
            "properties": {"analysisCompleteness": {"isComplete": complete, "coveragePercent": pct}}}],
    }]}


class Merge(unittest.TestCase):
    def test_rebase_prefixes_relative_uris_only(self):
        node = {"a": [{"artifactLocation": {"uri": "scripts/x.py"}},
                      {"artifactLocation": {"uri": "https://example.com/y"}},
                      {"artifactLocation": {"uri": "/abs"}}]}
        ci._rebase(node, "skills/s/")
        self.assertEqual([n["artifactLocation"]["uri"] for n in node["a"]],
                         ["skills/s/scripts/x.py", "https://example.com/y", "/abs"])

    def test_merge_one_run_dedup_rules_tags_skill(self):
        m = ci.merge({
            "b-skill": sarif([result("B1", "HIGH", "SKILL.md")], rules=("A1", "B1")),
            "a-skill": sarif([result("A1", "MEDIUM", "scripts/x.py")], complete=False, pct=50.0),
        })
        self.assertEqual(len(m["runs"]), 1)
        run = m["runs"][0]
        self.assertEqual([r["id"] for r in run["tool"]["driver"]["rules"]], ["A1", "B1"])
        self.assertEqual([(r["properties"]["skill"], r["locations"][0]["physicalLocation"]
                           ["artifactLocation"]["uri"]) for r in run["results"]],
                         [("a-skill", "skills/a-skill/scripts/x.py"), ("b-skill", "skills/b-skill/SKILL.md")])
        inv = run["invocations"][0]
        self.assertTrue(inv["executionSuccessful"])
        self.assertEqual(len(inv["toolExecutionNotifications"]), 2)
        self.assertFalse(inv["properties"]["analysisCompleteness"]["a-skill"]["isComplete"])
        self.assertEqual(m["version"], "2.1.0")

    def test_merge_empty(self):
        self.assertIsNone(ci.merge({}))


class Gate(unittest.TestCase):
    def setUp(self):
        self.m = ci.merge({"s": sarif([
            result("C1", "CRITICAL", "a"), result("H1", "HIGH", "b"),
            result("H2", "HIGH", "c", suppressed=True), result("M1", "MEDIUM", "d"),
            result("L1", "LOW", "e")])})

    def ids(self, floor):
        return sorted(r["ruleId"] for r in ci.blocking(self.m, floor))

    def test_suppressed_never_blocks(self):
        self.assertEqual(self.ids("HIGH"), ["C1", "H1"])

    def test_floor(self):
        self.assertEqual(self.ids("CRITICAL"), ["C1"])
        self.assertEqual(self.ids("MEDIUM"), ["C1", "H1", "M1"])
        self.assertEqual(self.ids("LOW"), ["C1", "H1", "L1", "M1"])

    def test_no_report_blocks_nothing(self):
        self.assertEqual(ci.blocking(None, "HIGH"), [])

    def test_summary_rows(self):
        m = ci.merge({"s": sarif([result("H1", "HIGH", "b"), result("H2", "HIGH", "c", suppressed=True)],
                                 complete=False, pct=75.0)})
        text = ci.summary(m, "HIGH", {"broken": "exit 2: boom"})
        self.assertIn("| s | HIGH 1 | 1 | 75% (partial) |", text)
        self.assertIn("| broken | scan failed: exit 2: boom |", text)

    def test_annotation(self):
        m = ci.merge({"s": sarif([result("H1", "HIGH", "x.py", line=7)])})
        self.assertEqual(ci.annotate(m["runs"][0]["results"][0]),
                         "::error file=skills/s/x.py,line=7,title=SkillSpector H1::H1 text")


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.skills = os.path.join(root, "skills")
        self.bl = os.path.join(root, "bl")
        self.work = os.path.join(root, "work")
        for d in (self.bl, self.work):
            os.makedirs(d)
        for name in ("one", "two"):
            os.makedirs(os.path.join(self.skills, name, "scripts", "__pycache__"))
            with open(os.path.join(self.skills, name, "SKILL.md"), "w") as f:
                f.write("---\nname: %s\n---\n" % name)
            open(os.path.join(self.skills, name, "scripts", "__pycache__", "x.pyc"), "w").close()
        os.makedirs(os.path.join(self.skills, "not-a-skill"))
        open(os.path.join(self.bl, "one.yaml"), "w").close()
        self.calls = []

    def fake_run(self, report=None, code=1):
        def run(cmd, **kwargs):
            self.calls.append(cmd)
            src = cmd[2]
            self.assertFalse(os.path.exists(os.path.join(src, "scripts", "__pycache__")))
            if report is not None:
                with open(cmd[cmd.index("--output") + 1], "w") as f:
                    json.dump(report, f)
            return mock.Mock(returncode=code, stdout="", stderr="Error: boom\n")
        return run

    def test_discover_and_stale(self):
        self.assertEqual(ci.discover(self.skills), ["one", "two"])
        open(os.path.join(self.bl, "gone.yaml"), "w").close()
        self.assertEqual(ci.stale_baselines(self.bl, ["one", "two"]), ["gone.yaml"])

    def test_scan_uses_baseline_and_clean_copy(self):
        with mock.patch.object(ci.subprocess, "run", self.fake_run(sarif([]))):
            name, rep, err = ci.scan("ss", "one", self.skills, self.bl, self.work)
            ci.scan("ss", "two", self.skills, self.bl, self.work)
        self.assertIsNone(err)
        self.assertIn("--no-llm", self.calls[0])
        self.assertEqual(self.calls[0][-2:], ["--baseline", os.path.join(self.bl, "one.yaml")])
        self.assertNotIn("--baseline", self.calls[1])

    def test_scan_error_exit(self):
        with mock.patch.object(ci.subprocess, "run", self.fake_run(None, code=2)):
            _, rep, err = ci.scan("ss", "one", self.skills, self.bl, self.work)
        self.assertIsNone(rep)
        self.assertIn("exit 2", err)

    def test_scan_unsuccessful_execution(self):
        with mock.patch.object(ci.subprocess, "run", self.fake_run(sarif([], ok=False))):
            _, rep, err = ci.scan("ss", "one", self.skills, self.bl, self.work)
        self.assertIsNone(rep)
        self.assertIn("executionSuccessful", err)

    def run_main(self, report, extra=()):
        out = os.path.join(self.tmp.name, "out.sarif")
        buf = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY")}
        with mock.patch.object(ci.subprocess, "run", self.fake_run(report)), \
                mock.patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = ci.main(["--skillspector", "ss", "--skills-dir", self.skills,
                            "--baselines", self.bl, "--output", out, "--jobs", "2", *extra])
        return code, buf.getvalue(), out

    def test_main_pass_writes_merged_sarif(self):
        code, text, out = self.run_main(sarif([result("H", "HIGH", "a", suppressed=True)]))
        self.assertEqual(code, 0, text)
        with open(out) as f:
            self.assertEqual(len(json.load(f)["runs"][0]["results"]), 2)
        self.assertIn("PASS", text)

    def test_main_fails_on_unsuppressed_high(self):
        code, text, _ = self.run_main(sarif([result("H", "HIGH", "scripts/a.py", line=3)]))
        self.assertEqual(code, 1)
        self.assertIn("BLOCKING H HIGH skills/one/scripts/a.py:3", text)

    def test_main_fails_on_stale_baseline(self):
        open(os.path.join(self.bl, "gone.yaml"), "w").close()
        code, text, _ = self.run_main(sarif([]))
        self.assertEqual(code, 1)
        self.assertIn("stale baseline", text)

    def test_main_unknown_skill_and_missing_scanner(self):
        code, _, _ = self.run_main(sarif([]), extra=["--skills", "nope"])
        self.assertEqual(code, 2)
        with mock.patch.object(ci.shutil, "which", lambda n: None), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ci.main(["--skills-dir", self.skills]), 2)


class RepoBaselines(unittest.TestCase):
    """Every committed baseline names a skill and gives a reason per rule."""

    def test_baselines(self):
        bl = os.path.join(REPO_ROOT, ".skillspector")
        skills = ci.discover(os.path.join(REPO_ROOT, "skills"))
        self.assertEqual(ci.stale_baselines(bl, skills), [])
        for f in sorted(os.listdir(bl)) if os.path.isdir(bl) else []:
            with self.subTest(baseline=f), open(os.path.join(bl, f), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("version: 2", text)
            self.assertEqual(text.count("  - id:"), text.count("    reason:"))
            self.assertNotIn("fingerprints:", text)  # glob rules only (see AGENTS.md)


if __name__ == "__main__":
    unittest.main()
