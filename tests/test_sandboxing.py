"""Tests for skills/sandboxing. Unit tests are pure: they build the bwrap
command and run the preflight checks with an injected environment and euid,
so they need no bwrap, no network and no real user changes. Run from the
repo root: python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("sandboxing"):
    raise unittest.SkipTest("sandboxing not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "skills", "sandboxing", "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(
        "sandboxing_" + name, os.path.join(SCRIPTS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sandbox = _load("sandbox")

WORK = "/fixture/work"
CA = "/fixture/ca.crt"
BASE_ENV = {"HOME": "/fixture/home", "PATH": "/usr/bin:/bin"}


def build(argv, env=None, euid=1000, work=WORK, ca_copy=CA):
    opts = sandbox.parse_args(argv)
    return sandbox.build_command(opts, dict(BASE_ENV, **(env or {})), euid, work, ca_copy)


def pairs(cmd, flag):
    """Values following each occurrence of a bwrap flag with one argument."""
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == flag]


def triples(cmd, flag):
    """(a, b) after each occurrence of a bwrap flag with two arguments."""
    return [(cmd[i + 1], cmd[i + 2]) for i, a in enumerate(cmd) if a == flag]


def bwrap_part(cmd):
    """The bwrap options only (from bwrap up to its "--")."""
    start = cmd.index("bwrap")
    return cmd[start:cmd.index("--", start)]


def setenvs(cmd):
    return dict(triples(bwrap_part(cmd), "--setenv"))


class TempDirs(unittest.TestCase):
    def mkdir(self, mode=0o755):
        d = tempfile.mkdtemp()
        os.chmod(d, mode)
        self.addCleanup(shutil.rmtree, d, True)
        return d


class CommandTests(TempDirs):
    def test_command_starts_with_env_i(self):
        self.assertEqual(build(["--", "true"])[0:2], ["env", "-i"])

    def test_root_caller_uses_setpriv(self):
        cmd = build(["--", "true"], euid=0)
        self.assertIn("setpriv", cmd)
        sp, bw = cmd.index("setpriv"), cmd.index("bwrap")
        self.assertLess(sp, bw)
        between = cmd[sp:bw]
        self.assertTrue(any(a.startswith("--reuid") for a in between))
        self.assertIn("--no-new-privs", between)
        self.assertIn("--bounding-set=-all", between)

    def test_non_root_caller_skips_setpriv(self):
        cmd = build(["--", "true"], euid=1000)
        self.assertNotIn("setpriv", cmd)
        self.assertEqual(cmd[2], "bwrap")

    def test_clearenv_and_home(self):
        cmd = build(["--", "true"])
        part = bwrap_part(cmd)
        self.assertIn("--clearenv", part)
        first_setenv = part.index("--setenv")
        self.assertLess(part.index("--clearenv"), first_setenv)
        self.assertEqual(setenvs(cmd)["HOME"], "/work")
        self.assertIn((WORK, "/work"), triples(part, "--bind"))
        self.assertEqual(pairs(part, "--chdir"), ["/work"])
        self.assertEqual(cmd[-1], "true")

    def test_ro_and_rw_binds(self):
        cmd = build(["--ro", "/fixture/src1:/dst1", "--ro", "/fixture/c",
                     "--rw", "/fixture/src2:/dst2", "--", "true"])
        part = bwrap_part(cmd)
        ro = triples(part, "--ro-bind")
        self.assertIn(("/fixture/src1", "/dst1"), ro)
        self.assertIn(("/fixture/c", "/fixture/c"), ro)
        self.assertIn(("/fixture/src2", "/dst2"), triples(part, "--bind"))

    def test_path_includes_bin_of_ro_binds(self):
        rt = self.mkdir()
        os.mkdir(os.path.join(rt, "bin"))
        plain = self.mkdir()
        cmd = build(["--ro", rt + ":/opt/rt", "--ro", plain, "--", "node"])
        path = setenvs(cmd)["PATH"].split(":")
        self.assertEqual(path[0], "/opt/rt/bin")
        self.assertNotIn(os.path.join(plain, "bin"), path)
        self.assertIn("/usr/bin", path)

    def test_no_net(self):
        env = {"HTTPS_PROXY": "http://proxy.example:3128",
               "no_proxy": "localhost"}
        cmd = build(["--no-net", "--", "true"], env=env, ca_copy=None)
        part = bwrap_part(cmd)
        self.assertNotIn("--share-net", part)
        self.assertNotIn("HTTPS_PROXY", setenvs(cmd))
        self.assertNotIn("/ca.crt", [d for _, d in triples(part, "--ro-bind")])

        cmd = build(["--", "true"], env=env)
        part = bwrap_part(cmd)
        self.assertIn("--share-net", part)
        envs = setenvs(cmd)
        self.assertEqual(envs["HTTPS_PROXY"], "http://proxy.example:3128")
        self.assertEqual(envs["no_proxy"], "localhost")
        self.assertIn((CA, "/ca.crt"), triples(part, "--ro-bind"))
        for name in ("SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
                     "NODE_EXTRA_CA_CERTS"):
            self.assertEqual(envs[name], "/ca.crt")

    def test_setenv_and_pass_env(self):
        cmd = build(["--setenv", "API_KEY=placeholder", "--pass-env", "LANG_X",
                     "--", "true"], env={"LANG_X": "abc"})
        envs = setenvs(cmd)
        self.assertEqual(envs["API_KEY"], "placeholder")
        self.assertEqual(envs["LANG_X"], "abc")
        opts = sandbox.parse_args(["--pass-env", "MISSING_X", "--", "true"])
        errors = sandbox.preflight(opts, dict(BASE_ENV), 1000)
        self.assertTrue(any("MISSING_X" in e for e in errors), errors)

    def test_limits_use_prlimit(self):
        cmd = build(["--mem", "256", "--nproc", "30", "--cpu", "5", "--", "sh", "-c", "x"])
        i = cmd.index("prlimit")
        self.assertGreater(i, cmd.index("bwrap"))
        self.assertEqual(cmd[i:i + 5],
                         ["prlimit", "--as=268435456", "--nproc=30", "--cpu=5", "--"])
        self.assertEqual(cmd[i + 5:], ["sh", "-c", "x"])
        self.assertNotIn("prlimit", build(["--", "true"]))


class PreflightTests(TempDirs):
    def make_home(self):
        home = self.mkdir()
        for sub in (".ssh", ".aws", ".config/gh", ".claude", ".codex",
                    ".local/share/opencode", "project"):
            os.makedirs(os.path.join(home, sub))
        return home

    def errors(self, argv, env=None, euid=1000):
        opts = sandbox.parse_args(argv)
        return sandbox.preflight(opts, dict(BASE_ENV, **(env or {})), euid)

    def test_preflight_refuses_sensitive_binds(self):
        home = self.make_home()
        env = {"HOME": home}
        targets = [home, "/root"] + [os.path.join(home, s) for s in (
            ".ssh", ".aws", ".config/gh", ".claude", ".codex",
            ".local/share/opencode")]
        for target in targets:
            for flag in ("--ro", "--rw"):
                with self.subTest(target=target, flag=flag):
                    errs = self.errors([flag, target, "--", "true"], env)
                    self.assertTrue(any("sensitive" in e for e in errs), errs)
                    errs = self.errors(["--allow-sensitive", flag, target, "--", "true"], env)
                    self.assertFalse(any("sensitive" in e for e in errs), errs)
        # a parent of the home folder is refused too; a project inside it is not
        errs = self.errors(["--ro", os.path.dirname(home), "--", "true"], env)
        self.assertTrue(any("sensitive" in e for e in errs), errs)
        self.assertEqual(self.errors(["--ro", os.path.join(home, "project"), "--", "true"], env), [])

    def test_preflight_refuses_proxy_credentials(self):
        env = {"HTTPS_PROXY": "http://u:p@h:1"}
        errs = self.errors(["--", "true"], env)
        self.assertTrue(any("HTTPS_PROXY" in e for e in errs), errs)
        self.assertFalse(any("u:p" in e for e in errs), "error must not print the credentials")
        self.assertEqual(self.errors(["--allow-proxy-credentials", "--", "true"], env), [])
        self.assertEqual(self.errors(["--no-net", "--", "true"], env), [])
        self.assertEqual(self.errors(["--", "true"], {"HTTPS_PROXY": "http://h:1"}), [])

    def test_preflight_unreadable_parent(self):
        base = self.mkdir()
        private = os.path.join(base, "private")
        os.mkdir(private, 0o700)
        src = os.path.join(private, "data")
        os.mkdir(src, 0o755)
        errs = self.errors(["--ro", src, "--", "true"], euid=0)
        self.assertTrue(any("'%s'" % private in e for e in errs), errs)
        os.chmod(private, 0o755)
        self.assertEqual(self.errors(["--ro", src, "--", "true"], euid=0), [])

    def test_preflight_missing_source(self):
        errs = self.errors(["--ro", "/fixture/does-not-exist", "--", "true"])
        self.assertTrue(any("does-not-exist" in e for e in errs), errs)

    def test_refuses_user_root(self):
        errs = self.errors(["--user", "root", "--", "true"], euid=0)
        self.assertTrue(any("root" in e for e in errs), errs)

    def test_requires_command(self):
        errs = self.errors([])
        self.assertTrue(any("command" in e for e in errs), errs)


class MainTests(unittest.TestCase):
    def test_show_prints_command(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": "/fixture/home", "PATH": "/usr/bin:/bin"},
                             clear=True), contextlib.redirect_stdout(out):
            status = sandbox.main(["--show", "--", "true"])
        self.assertEqual(status, 0)
        text = out.getvalue()
        self.assertTrue(text.startswith("env -i "), text)
        self.assertIn("bwrap", text)
        self.assertTrue(text.rstrip().endswith("true"), text)

    def test_preflight_error_exits_2(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": "/fixture/home"}, clear=True), \
                contextlib.redirect_stderr(err):
            status = sandbox.main(["--show", "--user", "root", "--", "true"])
        self.assertEqual(status, 2)
        self.assertIn("root", err.getvalue())

    def test_version(self):
        self.assertRegex(sandbox.VERSION, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
