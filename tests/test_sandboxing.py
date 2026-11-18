"""Tests for skills/sandboxing. Unit tests are pure: they build the bwrap
command and run the preflight checks with an injected environment and euid,
so they need no bwrap, no network and no real user changes. Run from the
repo root: python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
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

    def test_preflight_rw_not_writable(self):
        src = self.mkdir(0o755)  # owned by the test's user: not the sandbox user
        errs = self.errors(["--rw", src, "--", "true"], euid=0)
        self.assertTrue(any("'%s'" % src in e and "writable" in e for e in errs), errs)
        self.assertEqual(self.errors(["--ro", src, "--", "true"], euid=0), [])
        os.chmod(src, 0o777)
        self.assertEqual(self.errors(["--rw", src, "--", "true"], euid=0), [])

    def test_preflight_rw_file_not_writable(self):
        f = os.path.join(self.mkdir(), "data.txt")
        with open(f, "w") as fh:
            fh.write("x")
        os.chmod(f, 0o644)
        errs = self.errors(["--rw", f, "--", "true"], euid=0)
        self.assertTrue(any("writable" in e for e in errs), errs)
        os.chmod(f, 0o666)
        self.assertEqual(self.errors(["--rw", f, "--", "true"], euid=0), [])

    def test_mem_warning_for_node(self):
        rt = self.mkdir()
        os.mkdir(os.path.join(rt, "bin"))
        open(os.path.join(rt, "bin", "node"), "w").close()
        def warns(argv):
            return sandbox.warnings(sandbox.parse_args(argv))
        low = warns(["--mem", "512", "--ro", rt, "--", "x"])
        self.assertTrue(any("--mem" in w and "Node" in w for w in low), low)
        self.assertTrue(warns(["--mem", "512", "--", "node", "-e", "1"]))
        self.assertEqual(warns(["--mem", str(sandbox.NODE_MIN_MEM_MB), "--ro", rt, "--", "x"]), [])
        self.assertEqual(warns(["--mem", "512", "--", "python3", "-c", "1"]), [])
        self.assertEqual(warns(["--ro", rt, "--", "x"]), [])

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


SKILL_DIR = os.path.dirname(SCRIPTS)
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
# options of other commands the docs use (opencode run in the worked
# example); every other --option must belong to sandbox.py or leak_test.py
FOREIGN_OPTIONS = {"--standalone", "--archived", "--auto", "--format", "--model"}


def _parser_options(module):
    """Option strings of a script's parser, read from its --help output."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        module.parse_args(["--help"])
    return set(OPTION.findall(out.getvalue()))


class DocsTests(unittest.TestCase):
    def test_skill_md_names_only_real_options(self):
        """Every --option in SKILL.md and references/*.md is an option of
        sandbox.py or leak_test.py, or listed in FOREIGN_OPTIONS."""
        known = (_parser_options(sandbox) | _parser_options(_load("leak_test"))
                 | FOREIGN_OPTIONS)
        docs = [os.path.join(SKILL_DIR, "SKILL.md")]
        refs = os.path.join(SKILL_DIR, "references")
        if os.path.isdir(refs):
            docs += [os.path.join(refs, n) for n in sorted(os.listdir(refs))
                     if n.endswith(".md")]
        for path in docs:
            self.assertTrue(os.path.isfile(path), path)
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    for opt in OPTION.findall(line):
                        with self.subTest(file=os.path.basename(path), line=n):
                            self.assertIn(opt, known)


SANDBOX_PY = os.path.join(SCRIPTS, "sandbox.py")
LEAK_TEST_PY = os.path.join(SCRIPTS, "leak_test.py")


def _bwrap_works():
    """True when bwrap can create the namespaces the sandbox needs here
    (bwrap --unshare-all --uid 1000 with a read-only /usr)."""
    if not shutil.which("bwrap"):
        return False
    probe = (["bwrap", "--unshare-all", "--uid", "1000", "--gid", "1000"]
             + sandbox._usr_binds() + ["--", "/usr/bin/true"])
    try:
        return subprocess.run(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(_bwrap_works(), "bwrap with user namespaces is not usable here")
class IntegrationTests(unittest.TestCase):
    def run_sandbox(self, args, env=None, timeout=120):
        return subprocess.run([sys.executable, SANDBOX_PY] + args, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=timeout)

    def mkdir(self):
        d = tempfile.mkdtemp(prefix="sandboxing-test.", dir="/tmp")
        os.chmod(d, 0o755)
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def test_leak_test_passes(self):
        r = subprocess.run([sys.executable, LEAK_TEST_PY], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(lines[-1], "PASS", r.stdout)
        self.assertFalse(any(l.startswith("LEAK") for l in lines), r.stdout)

    def test_env_not_visible(self):
        marker = "sandboxing-env-marker-7f3a"
        env = dict(os.environ, SECRET_X=marker)
        r = self.run_sandbox(["--no-net", "--", "env"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HOME=/work", r.stdout)
        self.assertNotIn(marker, r.stdout)
        self.assertNotIn("SECRET_X", r.stdout)

    def test_caller_home_not_visible(self):
        home = os.path.expanduser("~")
        r = self.run_sandbox(["--no-net", "--", "sh", "-c", 'test -e "$1"', "sh", home])
        self.assertEqual(r.returncode, 1, r.stderr)
        r = self.run_sandbox(["--no-net", "--", "sh", "-c", 'test -e "$1"', "sh", "/work"])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_runtime_outside_usr(self):
        rt = self.mkdir()
        os.mkdir(os.path.join(rt, "bin"), 0o755)
        hello = os.path.join(rt, "bin", "hello")
        with open(hello, "w") as f:
            f.write("#!/bin/sh\necho hello-from-runtime\n")
        os.chmod(hello, 0o755)
        r = self.run_sandbox(["--no-net", "--ro", rt + ":/opt/rt", "--", "hello"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "hello-from-runtime")

    def test_work_folder_usable_after_run(self):
        work = os.path.join(self.mkdir(), "work")
        r = self.run_sandbox(["--no-net", "--work", work, "--", "sh", "-c",
                              "echo made-inside > /work/f"])
        self.assertEqual(r.returncode, 0, r.stderr)
        f = os.path.join(work, "f")
        with open(f) as fh:
            self.assertEqual(fh.read().strip(), "made-inside")
        os.remove(f)
        self.assertFalse(os.path.exists(f))
        shutil.rmtree(work)

    def test_rw_bind_writable_inside(self):
        data = os.path.join(self.mkdir(), "data")
        os.mkdir(data)
        os.chmod(data, 0o777)
        r = self.run_sandbox(["--no-net", "--rw", data + ":/data", "--",
                              "sh", "-c", "echo from-inside > /data/f"])
        self.assertEqual(r.returncode, 0, r.stderr)
        f = os.path.join(data, "f")
        with open(f) as fh:
            self.assertEqual(fh.read().strip(), "from-inside")
        os.remove(f)

    def test_exit_status_passed_through(self):
        r = self.run_sandbox(["--no-net", "--", "sh", "-c", "exit 7"])
        self.assertEqual(r.returncode, 7, r.stderr)
        work = os.path.join(self.mkdir(), "work")
        r = self.run_sandbox(["--no-net", "--work", work, "--", "sh", "-c", "exit 7"])
        self.assertEqual(r.returncode, 7, r.stderr)
        r = self.run_sandbox(["--no-net", "--cpu", "1", "--", "sh", "-c",
                              "while :; do :; done"], timeout=60)
        self.assertNotEqual(r.returncode, 0, r.stderr)

    def test_no_net_blocks_network(self):
        code = ("import socket\n"
                "try:\n"
                "    socket.create_connection(('192.0.2.1', 443), timeout=5)\n"
                "except OSError as exc:\n"
                "    print('blocked', exc)\n"
                "    raise SystemExit(3)\n")
        r = self.run_sandbox(["--no-net", "--", "python3", "-c", code])
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("blocked", r.stdout)


if __name__ == "__main__":
    unittest.main()
