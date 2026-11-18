#!/usr/bin/env python3
"""Leak self-test for sandbox.py: plant a random marker outside, look for it
from inside the sandbox.

    python3 leak_test.py [--user NAME] [--no-net]

The marker is planted in an environment variable of the sandbox.py process,
in the environment and command line of a long-running outside process, and
in a mode-600 file. Probes inside (run through sandbox.py) look for it in
env, /proc/*/environ, /proc/*/cmdline, the file, and with grep -r over /
(minus /proc, /dev, /sys and the read-only /usr); they also check that the
caller's home is hidden and /work is writable. Two `info` probes: HTTPS
through the caller's proxy (when one is set) and, from the host side, which
host user runs the sandboxed process.

Prints one `ok`, `LEAK` or `info` line per probe, then PASS or FAIL.
Exit 0 on PASS, 1 on FAIL, 2 when the sandbox can't run here. Stdlib only.
"""
import argparse
import os
import pwd
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

VERSION = "0.1.0"

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX_PY = os.path.join(HERE, "sandbox.py")
MARKER_VAR = "LEAK_TEST_SECRET"
HTTPS_URL = "https://pypi.org/simple/"
PROXY_VARS = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
              "ALL_PROXY", "all_proxy"]

# Runs inside the sandbox as: sh /probe/probe.sh HOME SECRET_HOST SECRET_BOUND HTTPS_URL
# The marker halves come from /probe/halves (one per line), so no argv holds
# the whole marker: grep reads it as a pattern from stdin (printf is a shell
# builtin, so it never shows in /proc/*/cmdline either).
PROBE_SH = r'''
{ read -r A; read -r B; } < /probe/halves
home=$1 secret_host=$2 secret_bound=$3 url=$4
has() { printf '%s%s\n' "$A" "$B" | grep -qaF -f - "$@" 2>/dev/null; }
say() { echo "$1 $2: $3"; }

env > /tmp/probe-env.txt
if has /tmp/probe-env.txt; then say LEAK env "marker in the environment"
else say ok env "marker not in the environment"; fi

if has /proc/[0-9]*/environ; then say LEAK proc-environ "marker in /proc/*/environ"
else say ok proc-environ "marker not in any visible /proc/*/environ"; fi

if has /proc/[0-9]*/cmdline; then say LEAK proc-cmdline "marker in /proc/*/cmdline"
else say ok proc-cmdline "marker not in any visible /proc/*/cmdline"; fi

found=no
for f in "$secret_host" "$secret_bound"; do
  [ -n "$f" ] || continue
  if cat "$f" >/dev/null 2>&1; then found="$f"; fi
done
if [ "$found" != no ]; then say LEAK secret-file "readable at $found"
else say ok secret-file "mode-600 file not readable"; fi

if [ -e "$home" ]; then say LEAK caller-home "$home is visible"
else say ok caller-home "$home not visible"; fi

dirs=
for d in /* /.[!.]*; do
  [ -e "$d" ] || continue
  [ -L "$d" ] && continue
  case "$d" in /proc|/dev|/sys|/usr) continue ;; esac
  dirs="$dirs $d"
done
if has -r $dirs; then say LEAK grep-root "marker found by grep -r over /"
else say ok grep-root "marker not found by grep -r over /:$dirs"; fi

if touch /work/.leak-test 2>/dev/null && rm -f /work/.leak-test; then
  say ok work-writable "/work is writable"
else say LEAK work-writable "/work is not writable"; fi

if [ -n "$url" ]; then
  if command -v curl >/dev/null 2>&1; then
    code=$(curl -sS -o /dev/null -m 20 -w '%{http_code}' "$url" 2>&1)
  else
    code=$(python3 -c 'import sys,urllib.request as u; print(u.urlopen(sys.argv[1], timeout=20).status)' "$url" 2>&1 | tail -n 1)
  fi
  say info https "$url -> $code"
fi
'''

EXPECTED = ["env", "proc-environ", "proc-cmdline", "secret-file", "caller-home",
            "grep-root", "work-writable"]


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="leak_test.py",
        description="Check that sandbox.py hides a planted secret on this machine.")
    p.add_argument("--user", metavar="NAME",
                   help="host user for sandbox.py --user (default: sandbox.py's)")
    p.add_argument("--no-net", action="store_true",
                   help="run the probes with sandbox.py --no-net (skips the HTTPS probe)")
    p.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    return p.parse_args(argv)


def _sandbox_cmd(opts, extra):
    cmd = [sys.executable, SANDBOX_PY]
    if opts.user:
        cmd += ["--user", opts.user]
    return cmd + extra


def _mkdir(dirs, mode):
    d = tempfile.mkdtemp(prefix="leak-test.", dir="/tmp")
    os.chmod(d, mode)
    dirs.append(d)
    return d


def _write(path, text, mode):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


def _proxy_set(env):
    return any(env.get(n) for n in PROXY_VARS)


def _find_process(argv, timeout=15):
    """(pid, uid) of a host process whose command line is exactly `argv`
    (sandbox.py and bwrap carry it too, but only as a suffix)."""
    want = [a.encode() for a in argv]
    deadline = time.time() + timeout
    while time.time() < deadline:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    args = f.read().split(b"\0")[:-1]
                if args == want:
                    return int(pid), os.stat("/proc/" + pid).st_uid
            except OSError:
                continue
        time.sleep(0.2)
    return None, None


def _host_user_probe(opts, work):
    """info line: which host user runs the sandboxed process (seen from outside)."""
    token = "leak-test-" + secrets.token_hex(6)
    inner = ["sh", "-c", "sleep 30", token]
    cmd = _sandbox_cmd(opts, ["--no-net", "--work", work, "--"] + inner)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        pid, uid = _find_process(inner)
    finally:
        proc.kill()
        proc.wait()
    if pid is None:
        return "info host-user: sandboxed process not found from the host side"
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = "?"
    return "info host-user: sandboxed process runs as host user %s (uid %d)" % (name, uid)


def run(opts):
    euid = os.geteuid()
    dirs, procs, lines = [], [], []
    try:
        check = subprocess.run(_sandbox_cmd(opts, ["--no-net", "--", "true"]),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, timeout=120)
        if check.returncode != 0:
            print(check.stdout.rstrip())
            print("leak_test.py: the sandbox can't run here (sandbox.py exit %d)"
                  % check.returncode, file=sys.stderr)
            return 2

        marker = "leak" + secrets.token_hex(16)
        half = len(marker) // 2

        probe = _mkdir(dirs, 0o755)
        _write(os.path.join(probe, "halves"),
               marker[:half] + "\n" + marker[half:] + "\n", 0o644)
        _write(os.path.join(probe, "probe.sh"), PROBE_SH, 0o644)

        # a mode-600 file in a folder the sandbox user may pass through
        secret_dir = _mkdir(dirs, 0o755)
        secret = os.path.join(secret_dir, "secret")
        _write(secret, marker + "\n", 0o600)

        # an outside process holding the marker in its environment and argv
        outside_env = dict(os.environ, LEAK_TEST_OUTSIDE=marker)
        procs.append(subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)", marker],
            env=outside_env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        env = dict(os.environ, **{MARKER_VAR: marker})
        extra = ["--ro", probe + ":/probe"]
        bound = ""
        if euid == 0:
            # bind the root-only file: only a non-root sandbox user keeps it out
            extra += ["--ro", secret_dir + ":/leak-files"]
            bound = "/leak-files/secret"
        if opts.no_net:
            extra.append("--no-net")
        url = HTTPS_URL if not opts.no_net and _proxy_set(env) else ""
        home = os.path.expanduser("~")
        r = subprocess.run(
            _sandbox_cmd(opts, extra + ["--", "sh", "/probe/probe.sh",
                                        home, secret, bound, url]),
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=600)
        if r.returncode == 2 and not r.stdout:
            print(r.stderr.rstrip(), file=sys.stderr)
            return 2
        seen = set()
        for line in r.stdout.splitlines():
            word, _, rest = line.partition(" ")
            if word in ("ok", "LEAK", "info"):
                lines.append(line)
                seen.add(rest.split(":", 1)[0])
        for name in EXPECTED:
            if name not in seen:
                lines.append("LEAK %s: probe did not report (sandbox exit %d)"
                             % (name, r.returncode))
        if r.returncode != 0 and r.stderr.strip():
            lines.append("info stderr: " + r.stderr.strip().splitlines()[-1])
        if not url:
            lines.append("info https: skipped (%s)"
                         % ("--no-net" if opts.no_net else "no proxy set"))

        work = os.path.join(_mkdir(dirs, 0o755), "work")
        lines.append(_host_user_probe(opts, work))
    finally:
        for p in procs:
            p.kill()
            p.wait()
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)

    for line in lines:
        print(line)
    failed = any(l.startswith("LEAK") for l in lines)
    print("FAIL" if failed else "PASS")
    return 1 if failed else 0


def main(argv=None):
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    if opts.user == "root":
        print("leak_test.py: --user root is refused", file=sys.stderr)
        return 2
    return run(opts)


if __name__ == "__main__":
    sys.exit(main())
