"""Install NVIDIA SkillSpector (scanner) and its skill-inspector agent skill.

Usage: python scripts/install.py [--install-mcp] [--ref TAG] [--dry-run] ...
Stdlib only. Exit 0 on success, 1 when a step fails, 2 on bad usage.
"""

import argparse
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - runs fixed installer commands
import sys
import tempfile
import urllib.request

VERSION = "0.1.1"
DEFAULT_REF = "v2.13.6"
UV_VERSION = "0.11.32"
SKILLS_CLI = "skills@1.9.0"
REPO = "https://github.com/NVIDIA/skillspector.git"
SKILL_URL = "https://github.com/NVIDIA/SkillSpector/tree/{ref}/skills/skill-inspector"
UV_INSTALLER = "https://github.com/astral-sh/uv/releases/download/{v}/uv-installer.{ext}"
WINDOWS = platform.system() == "Windows"


class StepError(Exception):
    pass


def log(msg):
    print(f"[skillspector-install] {msg}", flush=True)


def run(cmd, dry, capture=False):
    log("$ " + " ".join(cmd))
    if dry:
        return ""
    try:
        res = subprocess.run(  # nosec B603 - list argv, no shell
            cmd, check=False, text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise StepError(f"not found: {cmd[0]}") from exc
    if res.returncode != 0:
        detail = (res.stderr or "").strip() if capture else ""
        raise StepError(f"exit {res.returncode}: {' '.join(cmd)} {detail}".strip())
    return res.stdout if capture else ""


def exe(name):
    return name + (".exe" if WINDOWS else "")


def find_uv():
    found = shutil.which("uv")
    if found:
        return found
    home = os.path.expanduser("~")
    for d in (os.path.join(home, ".local", "bin"), os.path.join(home, ".cargo", "bin")):
        cand = os.path.join(d, exe("uv"))
        if os.path.isfile(cand):
            return cand
    return None


def install_uv(dry):
    ext = "ps1" if WINDOWS else "sh"
    url = UV_INSTALLER.format(v=UV_VERSION, ext=ext)
    os.environ["UV_NO_MODIFY_PATH"] = "1"  # don't edit shell profiles
    log(f"uv not found; installing uv {UV_VERSION} from {url}")
    if dry:
        log("(dry run) would download and run the uv installer")
        return "uv"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"uv-installer.{ext}")
        with urllib.request.urlopen(url, timeout=60) as resp, open(path, "wb") as out:  # nosec B310 - fixed https URL
            out.write(resp.read())
        if WINDOWS:
            run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path], dry)
        else:
            run(["sh", path], dry)
    uv = find_uv()
    if not uv:
        raise StepError("uv installer finished but uv was not found in ~/.local/bin")
    log(f"uv installed at {uv}; add its folder to PATH for later shells")
    return uv


def tool_bin_dir(uv, dry):
    if dry:
        return None
    return run([uv, "tool", "dir", "--bin"], dry, capture=True).strip() or None


def scanner_path(uv, dry):
    bindir = tool_bin_dir(uv, dry)
    if bindir:
        cand = os.path.join(bindir, exe("skillspector"))
        if os.path.isfile(cand):
            return cand, bindir
    return shutil.which("skillspector"), bindir


def installed_version(path):
    if not path:
        return None
    try:
        out = subprocess.run(  # nosec B603
            [path, "--version"], capture_output=True, text=True, timeout=120, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"v?(\d+\.\d+\.\d+\S*)", out)
    return m.group(1) if m else None


def mcp_extra_installed(uv):
    """True when `uv tool list --show-extras` shows skillspector with [mcp]."""
    try:
        out = subprocess.run(  # nosec B603
            [uv, "tool", "list", "--show-extras"], capture_output=True, text=True,
            timeout=120, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in out.splitlines():
        if line.startswith("skillspector "):
            m = re.search(r"\[extras: ([^\]]*)\]", line)
            return bool(m) and "mcp" in [e.strip() for e in m.group(1).split(",")]
    return False


def mcp_registered():
    """True when the claude CLI already has an MCP server named skillspector."""
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        return subprocess.run(  # nosec B603
            [claude, "mcp", "get", "skillspector"], capture_output=True, text=True,
            timeout=120, check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_scanner(args, uv):
    want = args.ref.lstrip("v")
    path, _ = scanner_path(uv, args.dry_run)
    have = installed_version(path)
    has_extra = bool(have) and mcp_extra_installed(uv)
    # A reinstall without [mcp] would break an MCP server registered earlier.
    keep_mcp = not args.install_mcp and (has_extra or mcp_registered())
    want_mcp = args.install_mcp or keep_mcp
    if have == want and not args.force and (has_extra or not want_mcp):
        log(f"skillspector {have} already installed at {path}; skipping (--force reinstalls)")
        return path or "skillspector"
    if keep_mcp:
        log("keeping the [mcp] extra (installed before, or an MCP server named skillspector exists)")
    extra = "[mcp]" if want_mcp else ""
    spec = f"skillspector{extra} @ git+{REPO}@{args.ref}"
    cmd = [uv, "tool", "install", "--python", args.python]
    if have or args.force:
        cmd.append("--force")
    run(cmd + [spec], args.dry_run)
    if args.dry_run:
        return "skillspector"
    path, bindir = scanner_path(uv, args.dry_run)
    have = installed_version(path)
    if not have:
        raise StepError("skillspector installed but `skillspector --version` failed")
    log(f"skillspector {have} at {path}")
    on_path = bindir and any(
        os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(bindir))
        for p in os.environ.get("PATH", "").split(os.pathsep) if p
    )
    if bindir and not on_path:
        log(f"note: {bindir} is not on PATH; run `{uv} tool update-shell` or use the full path")
    return path


def install_skill(args):
    npx = shutil.which("npx")
    if not npx:
        raise StepError("Node.js is missing (it provides npx): install it, or rerun with --skip-skill")
    cmd = [npx, "-y", SKILLS_CLI, "add", SKILL_URL.format(ref=args.ref),
           "--skill", "skill-inspector", "-g", "-y"]
    for agent in args.agent or ["claude-code"]:
        cmd += ["-a", agent]
    run(cmd, args.dry_run)


def install_mcp(args, scanner):
    claude = shutil.which("claude")
    if not claude:
        raise StepError("claude CLI not found; add the MCP server to your agent by hand: "
                        f"command `{scanner} mcp` (stdio)")
    exists = False if args.dry_run else mcp_registered()
    if exists and not args.force:
        log("MCP server `skillspector` already configured; skipping (--force replaces it)")
        return
    if exists:
        run([claude, "mcp", "remove", "--scope", args.mcp_scope, "skillspector"], args.dry_run)
    run([claude, "mcp", "add", "--scope", args.mcp_scope, "skillspector", "--",
         scanner, "mcp"], args.dry_run)


def parse(argv):
    p = argparse.ArgumentParser(description="Install NVIDIA SkillSpector and its skill-inspector skill.")
    p.add_argument("--ref", default=DEFAULT_REF, help=f"SkillSpector tag for scanner and skill (default {DEFAULT_REF})")
    p.add_argument("--python", default="3.13", help="Python for the scanner: 3.12 or 3.13 (YARA wheels)")
    p.add_argument("--install-mcp", action="store_true", help="also install the [mcp] extra and `claude mcp add` it")
    p.add_argument("--mcp-scope", default="user", choices=["local", "user", "project"], help="claude mcp scope (default user)")
    p.add_argument("--agent", action="append", help="skills CLI agent to install for (repeatable; default claude-code)")
    p.add_argument("--skip-skill", action="store_true", help="don't install the skill-inspector skill")
    p.add_argument("--skip-scanner", action="store_true", help="don't install the skillspector command")
    p.add_argument("--force", action="store_true", help="reinstall even when already installed")
    p.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = p.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", args.ref):
        p.error(f"invalid --ref: {args.ref!r}")
    if args.python not in ("3.12", "3.13"):
        log(f"warning: --python {args.python} may have no prebuilt YARA wheel")
    if args.install_mcp and args.skip_scanner:
        p.error("--install-mcp needs the scanner; drop --skip-scanner")
    return args


def main(argv=None):
    args = parse(argv)
    try:
        scanner = None
        if not args.skip_scanner:
            uv = find_uv() or install_uv(args.dry_run)
            log(f"using uv at {uv}")
            scanner = install_scanner(args, uv)
        if not args.skip_skill:
            install_skill(args)
        if args.install_mcp:
            install_mcp(args, scanner)
    except (StepError, OSError) as exc:
        log(f"FAILED: {exc}")
        return 1
    log("done. Next: restart the agent session, then read the skill-inspector skill.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
