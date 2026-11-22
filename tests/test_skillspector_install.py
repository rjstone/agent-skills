"""Tests for skills/skillspector-install. Pure: shutil.which and subprocess
are mocked and every run is a --dry-run, so no network, uv, npx or claude
is needed. Run from the repo root: python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("skillspector-install"):
    raise unittest.SkipTest("skillspector-install not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "skills", "skillspector-install", "scripts", "install.py")

spec = importlib.util.spec_from_file_location("skillspector_install", SCRIPT)
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)

TOOLS = {"uv": "/fake/bin/uv", "npx": "/fake/bin/npx", "claude": "/fake/bin/claude"}


def fake_which(present):
    return lambda name: present.get(name)


def no_subprocess(*args, **kwargs):
    raise AssertionError(f"subprocess.run called in a dry run: {args}")


class DryRun(unittest.TestCase):
    def run_main(self, argv, present=TOOLS, have=None):
        out = io.StringIO()
        with mock.patch.object(inst.shutil, "which", fake_which(present)), \
                mock.patch.object(inst.subprocess, "run", no_subprocess), \
                mock.patch.object(inst, "installed_version", lambda path: have), \
                contextlib.redirect_stdout(out):
            code = inst.main(["--dry-run"] + argv)
        cmds = [line.split("$ ", 1)[1] for line in out.getvalue().splitlines() if "$ " in line]
        return code, cmds, out.getvalue()

    def test_default_pins_scanner_and_skill_to_one_ref(self):
        code, cmds, _ = self.run_main([])
        self.assertEqual(code, 0)
        ref = inst.DEFAULT_REF
        self.assertEqual(len(cmds), 2, cmds)
        self.assertIn(f"skillspector @ git+{inst.REPO}@{ref}", cmds[0])
        self.assertIn("--python 3.13", cmds[0])
        self.assertNotIn("[mcp]", cmds[0])
        self.assertIn(f"-y {inst.SKILLS_CLI} add", cmds[1])
        self.assertIn(inst.SKILL_URL.format(ref=ref), cmds[1])
        self.assertIn("-g -y -a claude-code", cmds[1])

    def test_skills_cli_is_pinned(self):
        self.assertRegex(inst.SKILLS_CLI, r"^skills@\d+\.\d+\.\d+$")

    def test_install_mcp_adds_extra_and_registers_server(self):
        code, cmds, _ = self.run_main(["--install-mcp", "--ref", "v9.9.9"])
        self.assertEqual(code, 0)
        self.assertIn("skillspector[mcp] @ git+", cmds[0])
        self.assertIn("@v9.9.9", cmds[0])
        self.assertTrue(cmds[-1].startswith("/fake/bin/claude mcp add --scope user skillspector -- "))
        self.assertTrue(cmds[-1].endswith(" mcp"))

    def test_matching_version_skips_scanner(self):
        code, cmds, out = self.run_main(["--skip-skill"], have=inst.DEFAULT_REF.lstrip("v"))
        self.assertEqual(code, 0)
        self.assertEqual(cmds, [])
        self.assertIn("already installed", out)

    def test_other_version_reinstalls_with_force(self):
        code, cmds, _ = self.run_main(["--skip-skill"], have="0.0.1")
        self.assertEqual(code, 0)
        self.assertIn(" --force ", cmds[0])

    def test_repeatable_agent(self):
        _, cmds, _ = self.run_main(["--skip-scanner", "--agent", "opencode", "--agent", "codex"])
        self.assertTrue(cmds[0].endswith("-a opencode -a codex"), cmds[0])

    def test_missing_npx_fails_with_hint(self):
        present = {"uv": TOOLS["uv"]}
        code, _, out = self.run_main(["--skip-scanner"], present=present)
        self.assertEqual(code, 1)
        self.assertIn("--skip-skill", out)

    def test_missing_uv_dry_run_plans_installer(self):
        with mock.patch.object(inst, "find_uv", lambda: None):
            code, _, out = self.run_main(["--skip-skill"], present={"npx": TOOLS["npx"]})
        self.assertEqual(code, 0)
        self.assertIn("uv-installer.", out)
        self.assertIn(inst.UV_VERSION, out)


class Args(unittest.TestCase):
    def parse_error(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            inst.parse(argv)
        return cm.exception.code

    def test_rejects_shell_metacharacters_in_ref(self):
        self.assertEqual(self.parse_error(["--ref", "v1;rm -rf"]), 2)

    def test_mcp_needs_scanner(self):
        self.assertEqual(self.parse_error(["--install-mcp", "--skip-scanner"]), 2)

    def test_bad_mcp_scope(self):
        self.assertEqual(self.parse_error(["--mcp-scope", "global"]), 2)


if __name__ == "__main__":
    unittest.main()
