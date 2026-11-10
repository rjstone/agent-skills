"""Load an opencode v2 plugin in a throwaway headless server and print what it registered.

Starts `opencode serve` on 127.0.0.1 with every XDG directory in a temp folder
(nothing touches your real config, data or sessions), lists the plugin in that
config's `plugins`, waits until the plugin is loaded, then prints its
`/api/plugin` entry (parts found, status) and the agents, skills, references
and MCP servers the server reports, plus plugin lines from the server log.
Optionally calls one RPC method. No model or credentials needed. Stdlib only.

    python scripts/plugin_probe.py <plugin-dir>
    python scripts/plugin_probe.py <plugin-dir> --rpc my-plugin/ping --input "{}"
    python scripts/plugin_probe.py <plugin-dir> --opencode <path-to-opencode> --json

Needs the v2 CLI: `npm install @opencode/cli@<version>` (bun skips the
postinstall that fetches the binary), then pass `--opencode
node_modules/.bin/opencode` or put it on PATH. Agents, skills and references
from your real global folders (e.g. ~/.claude/skills) still show up: only
opencode's own XDG folders are isolated.

Exit codes: 0 plugin active, 1 plugin missing or not active, 2 setup error.
"""
import argparse
import base64
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    return ANSI.sub("", text)


def find_password(log):
    """The password `opencode serve --print-logs` prints at startup, or None."""
    m = re.search(r"server password (\S+)", strip_ansi(log))
    return m.group(1) if m else None


def location_query(directory):
    """`location` is an object query parameter: location[directory]=<dir>."""
    return urllib.parse.urlencode({"location[directory]": directory})


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def plugin_entry(plugins, plugin_dir):
    """The /api/plugin entry loaded from plugin_dir (by source path), or None."""
    for p in plugins:
        path = (p.get("source") or {}).get("path")
        if path and same_path(path, plugin_dir):
            return p
    return None


def plugin_log_lines(log, plugin_dir):
    """Server log lines about loading plugins, and warnings/errors naming the plugin."""
    out = []
    for line in strip_ansi(log).splitlines():
        if "loading plugin" in line or (
            plugin_dir in line and re.search(r"level=(ERROR|WARN)", line)
        ):
            out.append(line)
    return out


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, opencode, plugin_dir, port):
        self.tmp = tempfile.mkdtemp(prefix="plugin-probe-")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)
        self.env = dict(os.environ)
        for name in ("CONFIG", "DATA", "CACHE", "STATE"):
            self.env[f"XDG_{name}_HOME"] = os.path.join(self.tmp, "xdg", name.lower())
        conf_dir = os.path.join(self.env["XDG_CONFIG_HOME"], "opencode")
        os.makedirs(conf_dir)
        with open(os.path.join(conf_dir, "opencode.jsonc"), "w", encoding="utf-8") as f:
            json.dump({"plugins": [plugin_dir]}, f)
        self.log_path = os.path.join(self.tmp, "serve.log")
        self.base = f"http://127.0.0.1:{port}"
        self.password = None
        # Local server: never route through an HTTP(S) proxy from the environment.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cmd = [opencode, "serve", "--hostname", "127.0.0.1", "--port", str(port),
               "--print-logs", "--log-level", "info"]
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
            else {"start_new_session": True}
        self.log_file = open(self.log_path, "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(cmd, cwd=self.project, env=self.env,
                                         stdout=self.log_file, stderr=subprocess.STDOUT, **kwargs)
        except OSError:
            self.log_file.close()
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise

    def log(self):
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def wait_ready(self, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("opencode serve exited:\n" + strip_ansi(self.log())[-2000:])
            self.password = self.password or find_password(self.log())
            if self.password:
                try:
                    self.get("/api/plugin")
                    return
                except OSError:
                    pass
            time.sleep(0.25)
        raise RuntimeError("opencode serve did not answer in time")

    def request(self, method, path, body=None):
        sep = "&" if "?" in path else "?"
        url = f"{self.base}{path}{sep}{location_query(self.project)}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        token = base64.b64encode(f"opencode:{self.password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        try:
            with self.opener.open(req, timeout=30) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as err:
            return json.loads(err.read() or b"null")

    def get(self, path):
        return (self.request("GET", path) or {}).get("data")

    def stop(self, keep):
        if self.proc.poll() is None:
            try:
                if os.name == "nt":
                    self.proc.terminate()
                else:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=10)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                if os.name != "nt":
                    os.killpg(self.proc.pid, signal.SIGKILL)
                else:
                    self.proc.kill()
        self.log_file.close()
        if not keep:
            shutil.rmtree(self.tmp, ignore_errors=True)


def probe(server, plugin_dir, timeout, rpc=None, rpc_input=None):
    """Wait for the plugin (plugins load per location, in the background, after the
    first request), then collect what the server reports."""
    end = time.monotonic() + timeout
    entry = None
    while time.monotonic() < end:
        entry = plugin_entry(server.get("/api/plugin") or [], plugin_dir)
        if entry and (entry.get("state") or {}).get("status") not in (None, "loading", "pending"):
            break
        time.sleep(0.5)
    result = {
        "plugin": entry,
        "agents": [a.get("id") for a in server.get("/api/agent") or []],
        "skills": [s.get("id") for s in server.get("/api/skill") or []],
        "references": [
            {k: r.get(k) for k in ("name", "path", "description")}
            for r in server.get("/api/reference") or []
        ],
        "mcp": [{"name": m.get("name"), "status": (m.get("status") or {}).get("status")}
                for m in server.get("/api/mcp") or []],
    }
    if rpc:
        rpc_id, _, method = rpc.partition("/")
        result["rpc"] = server.request("POST", f"/api/rpc/{rpc_id}/{method}", {"input": rpc_input})
    result["log"] = plugin_log_lines(server.log(), plugin_dir)
    return result


def print_report(r):
    p = r["plugin"]
    if p:
        parts = [k for k, v in (p.get("features") or {}).items() if v]
        print(f"plugin: {p.get('id')}  status={(p.get('state') or {}).get('status')}  parts={','.join(parts)}")
    else:
        print("plugin: NOT FOUND in /api/plugin")
    print("agents:", ", ".join(r["agents"]))
    print("skills:", ", ".join(r["skills"]))
    print("references:")
    for ref in r["references"]:
        print(f"  {ref['name']}: {ref['path']}  ({ref.get('description') or 'no description'})")
    print("mcp:", ", ".join(f"{m['name']}={m['status']}" for m in r["mcp"]) or "(none)")
    if "rpc" in r:
        print("rpc:", json.dumps(r["rpc"]))
    print("log:")
    for line in r["log"]:
        print("  " + line[:300])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plugin_dir", help="plugin folder (holds package.json)")
    ap.add_argument("--opencode", default=shutil.which("opencode"), help="opencode v2 binary")
    ap.add_argument("--port", type=int, default=0, help="default: a free port")
    ap.add_argument("--timeout", type=float, default=60, help="seconds to wait for server and plugin")
    ap.add_argument("--rpc", help="call <rpcID>/<method> after loading")
    ap.add_argument("--input", default="null", help="JSON input for --rpc (default null)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder (config, log)")
    args = ap.parse_args(argv)

    if not args.opencode:
        print("opencode not found: pass --opencode, or `npm install @opencode/cli@<version>`",
              file=sys.stderr)
        return 2
    plugin_dir = os.path.abspath(args.plugin_dir)
    if not os.path.isdir(plugin_dir):
        print(f"not a folder: {plugin_dir}", file=sys.stderr)
        return 2
    try:
        server = Server(args.opencode, plugin_dir, args.port or free_port())
    except OSError as err:
        print(f"cannot start {args.opencode}: {err}", file=sys.stderr)
        return 2
    try:
        server.wait_ready(args.timeout)
        result = probe(server, plugin_dir, args.timeout, args.rpc, json.loads(args.input))
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 2
    finally:
        server.stop(args.keep)
    if args.keep:
        result["temp"] = server.tmp
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)
        if args.keep:
            print("temp folder:", server.tmp)
    ok = result["plugin"] and (result["plugin"].get("state") or {}).get("status") == "active"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
