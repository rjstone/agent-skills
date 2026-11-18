#!/usr/bin/env python3
"""Run a command in a bubblewrap (bwrap) sandbox that hides the caller's
environment, processes and files.

    python3 sandbox.py [options] -- COMMAND [ARGS...]

The command sees an empty environment (plus what --setenv/--pass-env give
it), its own /proc, /dev and /tmp, read-only /usr and TLS files, a writable
/work (also HOME and the working directory) and only the binds asked for.
Started as root, bwrap runs as a non-root host user (setpriv). Not a
security boundary against hostile code. Linux only; stdlib only.
"""
import argparse
import os
import pwd
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

VERSION = "0.2.0"

DEFAULT_USER = "sandboxer"
SANDBOX_UID = 1000
BASE_PATH = ["/usr/local/bin", "/usr/bin", "/bin"]
PROXY_VARS = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy"]
CA_VARS = ["SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE",
           "NODE_EXTRA_CA_CERTS"]
SYSTEM_CA_BUNDLES = ["/etc/ssl/certs/ca-certificates.crt",
                     "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem"]
# home-relative folders that usually hold credentials
CREDENTIAL_DIRS = [".ssh", ".aws", ".config/gh", ".claude", ".codex",
                   ".local/share/opencode"]
# top-level paths that are symlinks into /usr on merged-/usr systems
USR_LINKS = ["/bin", "/lib", "/lib64", "/sbin"]
SHOW_TMP = "/tmp/sandbox.XXXXXX"  # nosec B108 - placeholder shown by --show, never created
# sandbox.py's own failures (usage, preflight, missing tools): 125, as env,
# timeout and chroot use, so they don't look like the command's own status
EXIT_SANDBOX_ERROR = 125
# --mem is an address-space limit; Node.js (V8) reserves this much virtual
# memory at startup (Node 22 fails to start below about 768 MB)
NODE_MIN_MEM_MB = 1024
NODE_COMMANDS = {"node", "npm", "npx", "nodejs"}

CHECK_PROBE = r'''
echo "uid: $(id -u) gid: $(id -g)"
echo "cwd: $(pwd)"
echo "environment variables:"; env | cut -d= -f1 | sort | sed 's/^/  /'
echo "/:"; ls -A / | sed 's/^/  /'
if [ -n "$1" ] && [ -e "$1" ]; then echo "caller home visible: YES"; else echo "caller home visible: no"; fi
if touch /work/.sandbox-check 2>/dev/null; then rm -f /work/.sandbox-check; echo "/work writable: yes"; else echo "/work writable: NO"; fi
'''


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_SANDBOX_ERROR, "%s: error: %s\n" % (self.prog, message))


def parse_args(argv):
    p = _Parser(
        prog="sandbox.py",
        description="Run COMMAND in a bubblewrap sandbox that hides the caller's "
                    "environment, processes and files (Linux).",
        usage="%(prog)s [options] -- COMMAND [ARGS...]")
    p.add_argument("--work", metavar="DIR",
                   help="writable folder mounted at /work, also HOME and the working "
                        "directory (default: a new temp folder, removed afterwards)")
    p.add_argument("--cwd", metavar="DIR",
                   help="working directory inside; relative to /work (default /work)")
    p.add_argument("--ro", action="append", default=[], metavar="SRC[:DEST]",
                   help="read-only bind (repeatable); DEST defaults to SRC")
    p.add_argument("--rw", action="append", default=[], metavar="SRC[:DEST]",
                   help="writable bind (repeatable)")
    p.add_argument("--setenv", action="append", default=[], metavar="NAME=VALUE",
                   help="set a variable inside (repeatable)")
    p.add_argument("--pass-env", action="append", default=[], metavar="NAME",
                   help="copy a caller variable in (repeatable; readable inside)")
    p.add_argument("--user", default=DEFAULT_USER, metavar="NAME",
                   help="host user that runs bwrap when started as root (default "
                        "%(default)s, created if missing); root is refused")
    p.add_argument("--no-net", action="store_true",
                   help="no network (default: shared, with the caller's proxy "
                        "variables and a CA copy at /ca.crt)")
    p.add_argument("--mem", type=int, metavar="MB", help="address-space limit")
    p.add_argument("--nproc", type=int, metavar="N", help="process limit")
    p.add_argument("--cpu", type=int, metavar="SEC", help="CPU-time limit")
    p.add_argument("--keep", action="store_true", help="keep the default work folder")
    p.add_argument("--allow-sensitive", action="store_true",
                   help="allow binding the caller's home, /root or credential folders")
    p.add_argument("--allow-proxy-credentials", action="store_true",
                   help="pass a proxy URL that contains user:password@")
    p.add_argument("--show", action="store_true",
                   help="print the command that would run and exit")
    p.add_argument("--check", action="store_true",
                   help="run a probe inside that prints what it can see")
    p.add_argument("--version", action="version", version="%(prog)s " + VERSION)
    p.add_argument("command", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    if "--" in argv:
        i = argv.index("--")
        opts = p.parse_args(argv[:i])
        opts.command = argv[i + 1:]
    else:
        opts = p.parse_args(argv)
    return opts


def split_bind(spec):
    """'SRC[:DEST]' -> (absolute SRC, DEST)."""
    src, sep, dest = spec.partition(":")
    src = os.path.abspath(os.path.expanduser(src)) if src else ""
    return src, (dest if sep else src)


def binds(opts):
    """[(flag, src, dest)] for --ro and --rw, in the order given per kind."""
    out = [("--ro", *split_bind(s)) for s in opts.ro]
    out += [("--rw", *split_bind(s)) for s in opts.rw]
    return out


def cwd_path(opts):
    """The working directory inside the sandbox."""
    if not opts.cwd:
        return "/work"
    return os.path.normpath(os.path.join("/work", opts.cwd))


def hosts_text():
    """A minimal /etc/hosts: localhost only (the host's own may name internal hosts)."""
    return "127.0.0.1\tlocalhost\n::1\tlocalhost ip6-localhost ip6-loopback\n"


def _real(path):
    return os.path.realpath(path)


def _sensitive_paths(env):
    homes = []
    for h in (env.get("HOME"), "/root"):
        if h and _real(h) not in homes:
            homes.append(_real(h))
    creds = [_real(os.path.join(h, d)) for h in homes for d in CREDENTIAL_DIRS]
    return homes, creds


def _is_sensitive(path, env):
    """A reason string when binding `path` would expose a home or credentials."""
    p = _real(path)
    homes, creds = _sensitive_paths(env)
    for target in homes + creds:
        if p == target or target.startswith(p.rstrip("/") + "/"):
            return "contains or is %s" % target
    for c in creds:
        if p.startswith(c + "/"):
            return "is inside %s" % c
    return None


def _proxy_has_credentials(value):
    try:
        parts = urlsplit(value if "://" in value else "http://" + value)
        return parts.username is not None or "@" in parts.netloc
    except ValueError:
        return "@" in value


def _sandbox_ids(user):
    try:
        pw = pwd.getpwnam(user)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return None, None


def _others_can(st, want, uid, gid):
    """Can a user that is neither root nor the owner (unless uid matches) do `want`
    (a combination of 4=read, 1=search/exec) on the file with stat `st`?"""
    if uid is not None and st.st_uid == uid:
        bits = (st.st_mode >> 6) & 7
    elif gid is not None and st.st_gid == gid:
        bits = (st.st_mode >> 3) & 7
    else:
        bits = st.st_mode & 7
    return bits & want == want


def _unreadable(path, euid, user, write=False):
    """The first folder or file on the way to `path` the sandbox user can't
    pass or read (or, with `write`, write at the end), or None. As root,
    judges by mode bits for the sandbox user; otherwise by os.access for the
    caller (who runs bwrap itself)."""
    real = _real(path)
    parts = [p for p in real.split("/") if p]
    chain = ["/"] + ["/" + "/".join(parts[:i + 1]) for i in range(len(parts))]
    if euid == 0:
        uid, gid = _sandbox_ids(user)
        for i, p in enumerate(chain):
            try:
                st = os.stat(p)
            except OSError:
                return p
            last = i == len(chain) - 1
            if not last:
                want = 1
            else:
                want = 5 if stat.S_ISDIR(st.st_mode) else 4
                if write:
                    want |= 2
            if not _others_can(st, want, uid, gid):
                return p
        return None
    for i, p in enumerate(chain):
        last = i == len(chain) - 1
        mode = (os.R_OK | (os.X_OK if os.path.isdir(p) else 0)) if last else os.X_OK
        if last and write:
            mode |= os.W_OK
        if not os.access(p, mode):
            return p
    return None


def preflight(opts, env, euid):
    """Error messages (empty when fine). Pure apart from reading the file
    system for the bind sources."""
    errors = []
    if not opts.command and not opts.check:
        errors.append("no command given: sandbox.py [options] -- COMMAND [ARGS...]")
    if opts.user == "root" or opts.user == "0":
        errors.append("--user root is refused: the sandbox must run as a non-root host user")
    for name in opts.pass_env:
        if name not in env:
            errors.append("--pass-env %s: the variable is not set in the caller's environment" % name)
    for item in opts.setenv:
        if "=" not in item or not item.split("=", 1)[0]:
            errors.append("--setenv %r: expected NAME=VALUE" % item)
    for flag, value in (("--mem", opts.mem), ("--nproc", opts.nproc), ("--cpu", opts.cpu)):
        if value is not None and value <= 0:
            errors.append("%s must be a positive number" % flag)

    checks = [(flag + " " + src, src, dest, True, flag == "--rw")
              for flag, src, dest in binds(opts)]
    if opts.work:
        # the work folder is chowned to the sandbox user, so only reachability counts
        checks.append(("--work " + opts.work, os.path.abspath(opts.work), "/work", False, False))
    for label, src, dest, must_exist, writable in checks:
        if not src:
            errors.append("%s: empty source path" % label)
            continue
        if not dest.startswith("/"):
            errors.append("%s: destination %r must be an absolute path" % (label, dest))
        if not opts.allow_sensitive:
            why = _is_sensitive(src, env)
            if why:
                errors.append("%s: refused, sensitive: the source %s (home folder or "
                              "credentials); bind a narrower folder, or pass "
                              "--allow-sensitive if you really mean it" % (label, why))
                continue
        if not os.path.exists(src):
            if must_exist:
                errors.append("%s: the source does not exist" % label)
                continue
            # a --work folder is created; check its nearest existing parent
            src = os.path.dirname(src)
            while src != "/" and not os.path.exists(src):
                src = os.path.dirname(src)
        bad = _unreadable(src, euid, opts.user)
        if bad:
            who = ("the sandbox user %r" % opts.user) if euid == 0 else "this user"
            errors.append("%s: '%s' is not readable or searchable by %s; move or copy "
                          "the data to a readable place (e.g. under /tmp), or make "
                          "that folder readable (chmod o+rx)" % (label, bad, who))
        elif writable and _unreadable(src, euid, opts.user, write=True):
            who = ("the sandbox user %r" % opts.user) if euid == 0 else "this user"
            errors.append("%s: '%s' is not writable by %s, so the bind would be "
                          "read-only inside; make it writable for that user (chmod "
                          "o+w, or chown it), copy the data into the --work folder, "
                          "or use --ro" % (label, src, who))

    cwd = cwd_path(opts)
    if opts.cwd and opts.work and cwd.startswith("/work/"):
        host_cwd = os.path.join(os.path.abspath(opts.work), os.path.relpath(cwd, "/work"))
        if not os.path.isdir(host_cwd):
            errors.append("--cwd %s: %s does not exist in the --work folder (%s); "
                          "create it before the run" % (opts.cwd, cwd, host_cwd))

    if not opts.no_net and not opts.allow_proxy_credentials:
        for name in PROXY_VARS:
            value = env.get(name)
            if value and not name.lower().startswith("no_") and _proxy_has_credentials(value):
                errors.append("%s contains credentials (user@); they would be readable "
                              "inside. Use a proxy that injects credentials itself, "
                              "--no-net, or --allow-proxy-credentials" % name)
    return errors


def warnings(opts):
    """Advice that doesn't stop the run (printed to stderr by main)."""
    out = []
    if opts.mem and opts.mem < NODE_MIN_MEM_MB:
        cmd = os.path.basename(opts.command[0]) if opts.command else ""
        node = cmd in NODE_COMMANDS or any(
            flag == "--ro" and os.path.exists(os.path.join(src, "bin", "node"))
            for flag, src, _ in binds(opts))
        if node:
            out.append("--mem %d limits address space, not memory use: Node.js "
                       "reserves large virtual ranges and may die at startup "
                       "(\"Failed to reserve virtual memory\", exit 133 or 134); "
                       "use --mem %d or more for Node-based commands"
                       % (opts.mem, NODE_MIN_MEM_MB))
    return out


def _usr_binds():
    """Read-only /usr plus /bin, /lib, /lib64, /sbin (symlinks or folders)."""
    out = ["--ro-bind", "/usr", "/usr"]
    for link in USR_LINKS:
        if os.path.islink(link):
            out += ["--symlink", os.readlink(link), link]
        elif os.path.isdir(link):
            out += ["--ro-bind", link, link]
    return out


def build_command(opts, env, euid, work, ca_copy, hosts=None):
    """The full command line: env -i [setpriv ...] bwrap ... -- [prlimit ...] COMMAND."""
    cmd = ["env", "-i"]
    if euid == 0:
        cmd += ["setpriv", "--reuid=" + opts.user, "--regid=" + opts.user,
                "--clear-groups", "--no-new-privs", "--bounding-set=-all",
                "--inh-caps=-all", "--"]
    net = not opts.no_net
    b = ["bwrap", "--unshare-all"]
    if net:
        b.append("--share-net")
    b += ["--die-with-parent", "--new-session",
          "--uid", str(SANDBOX_UID), "--gid", str(SANDBOX_UID)] + _usr_binds()
    b += ["--ro-bind-try", "/etc/alternatives", "/etc/alternatives",
          "--ro-bind-try", "/etc/ssl", "/etc/ssl"]
    if net:
        b += ["--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf"]
    if hosts:
        # before the caller's binds, so a --ro of their own /etc/hosts wins
        b += ["--ro-bind", hosts, "/etc/hosts"]
    b += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",  # nosec B108 - /tmp inside the sandbox: a private tmpfs
          "--bind", work, "/work"]
    path = []
    for flag, src, dest in binds(opts):
        b += ["--ro-bind" if flag == "--ro" else "--bind", src, dest]
        if flag == "--ro" and os.path.isdir(os.path.join(src, "bin")):
            d = dest.rstrip("/") + "/bin"
            if d not in path:
                path.append(d)
    if net and ca_copy:
        b += ["--ro-bind", ca_copy, "/ca.crt"]

    setenv = [("HOME", "/work"), ("PATH", ":".join(path + BASE_PATH)),
              ("LANG", "C.UTF-8"), ("TMPDIR", "/tmp")]  # nosec B108 - TMPDIR inside the sandbox: a private tmpfs
    if net:
        setenv += [(n, env[n]) for n in PROXY_VARS if env.get(n)]
        if ca_copy:
            setenv += [(n, "/ca.crt") for n in CA_VARS]
    setenv += [(n, env[n]) for n in opts.pass_env if n in env]
    setenv += [tuple(s.split("=", 1)) for s in opts.setenv if "=" in s]
    b.append("--clearenv")
    for name, value in setenv:
        b += ["--setenv", name, value]
    b += ["--chdir", cwd_path(opts), "--"]
    cmd += b

    limits = []
    if opts.mem:
        limits.append("--as=%d" % (opts.mem * 1024 * 1024))
    if opts.nproc:
        limits.append("--nproc=%d" % opts.nproc)
    if opts.cpu:
        limits.append("--cpu=%d" % opts.cpu)
    if limits:
        cmd += ["prlimit"] + limits + ["--"]
    command = opts.command
    if opts.check:
        command = ["sh", "-c", CHECK_PROBE, "sh", env.get("HOME", "")]
    return cmd + list(command)


def _ca_source(env):
    for path in [env.get("SSL_CERT_FILE")] + SYSTEM_CA_BUNDLES:
        if path and os.path.isfile(path) and os.access(path, os.R_OK):
            return path
    return None


def _tool_errors(opts, euid):
    errors = []
    tools = ["bwrap"] + (["setpriv"] if euid == 0 else [])
    if opts.mem or opts.nproc or opts.cpu:
        tools.append("prlimit")
    for tool in tools:
        if not shutil.which(tool):
            errors.append("%s not found: install it (bubblewrap for bwrap, util-linux "
                          "for setpriv and prlimit)" % tool)
    return errors


def _ensure_user(user):
    if _sandbox_ids(user)[0] is not None:
        return None
    if not shutil.which("useradd"):
        return "user %r does not exist and useradd is missing: create it, or pass --user" % user
    shell = "/usr/sbin/nologin" if os.path.exists("/usr/sbin/nologin") else "/bin/false"
    r = subprocess.run(["useradd", "-M", "-s", shell, user],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        return "useradd %s failed: %s" % (user, r.stdout.strip())
    return None


def _chown_tree(top, uid, gid):
    os.chown(top, uid, gid)
    for root, dirs, files in os.walk(top):
        for name in dirs + files:
            os.lchown(os.path.join(root, name), uid, gid)


def _userns_error(prefix):
    """Run a trivial bwrap with the same prefix; an error message if it fails."""
    probe = prefix + ["bwrap", "--unshare-all", "--uid", str(SANDBOX_UID),
                      "--gid", str(SANDBOX_UID)] + _usr_binds() + ["--", "/usr/bin/true"]
    try:
        r = subprocess.run(probe, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "bwrap could not start: %s" % e
    if r.returncode != 0:
        return ("bwrap cannot create user namespaces here (%s). Unprivileged user "
                "namespaces may be disabled (kernel.unprivileged_userns_clone, "
                "AppArmor's restrict_unprivileged_userns) or blocked by the container"
                % (r.stdout.strip() or "exit %d" % r.returncode))
    return None


class _Signalled(Exception):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _raise_signal(signum, frame):
    raise _Signalled(signum)


def _fail(errors):
    for e in errors:
        print("sandbox.py: error: " + e, file=sys.stderr)
    return EXIT_SANDBOX_ERROR


def main(argv=None):
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ)
    euid = os.geteuid()
    errors = preflight(opts, env, euid)
    if errors:
        return _fail(errors)
    for w in warnings(opts):
        print("sandbox.py: warning: " + w, file=sys.stderr)
    net = not opts.no_net

    if opts.show:
        work = os.path.abspath(opts.work) if opts.work else SHOW_TMP + "/work"
        ca = SHOW_TMP + "/ca.crt" if net and _ca_source(env) else None
        print(shlex.join(build_command(opts, env, euid, work, ca, SHOW_TMP + "/hosts")))
        return 0

    errors = _tool_errors(opts, euid)
    if not errors and euid == 0:
        err = _ensure_user(opts.user)
        if err:
            errors.append(err)
    if errors:
        return _fail(errors)
    prefix = build_command(opts, env, euid, "/", None)
    prefix = prefix[:prefix.index("bwrap")]
    err = _userns_error(prefix)
    if err:
        return _fail([err])

    # per-run files the sandbox user must read: CA copy, hosts, default work
    tmp = tempfile.mkdtemp(prefix="sandbox.", dir="/tmp")  # nosec B108 - mkdtemp makes a unique folder; under /tmp so the sandbox user can reach it
    os.chmod(tmp, 0o755)  # nosec B103 - the sandbox user must read the CA copy and hosts file
    hosts = os.path.join(tmp, "hosts")
    with open(hosts, "w") as f:
        f.write(hosts_text())
    os.chmod(hosts, 0o644)
    work = os.path.abspath(opts.work) if opts.work else os.path.join(tmp, "work")
    os.makedirs(work, exist_ok=True)
    if not opts.work:
        # the run's own output: owner only (the owner becomes the sandbox user)
        os.chmod(work, 0o700)
    ca_copy = None
    if net:
        src = _ca_source(env)
        if src:
            ca_copy = os.path.join(tmp, "ca.crt")
            shutil.copyfile(src, ca_copy)
            os.chmod(ca_copy, 0o644)
        else:
            print("sandbox.py: warning: no CA bundle found; HTTPS may fail inside",
                  file=sys.stderr)
    if euid == 0:
        uid, gid = _sandbox_ids(opts.user)
        _chown_tree(work, uid, gid)

    cmd = build_command(opts, env, euid, work, ca_copy, hosts)
    keep_tmp = opts.keep and not opts.work
    # SIGTERM (timeout, kill) or SIGHUP: stop the sandbox and still clean up;
    # subprocess.call kills its child when the wait is interrupted
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _raise_signal)
    try:
        status = subprocess.call(cmd)
    except KeyboardInterrupt:
        status = 130
    except _Signalled as e:
        status = 128 + e.signum
    finally:
        if keep_tmp:
            for f in (ca_copy, hosts):
                if f:
                    os.unlink(f)
            print("sandbox.py: kept work folder " + work, file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return 128 - status if status < 0 else status


if __name__ == "__main__":
    sys.exit(main())
