#!/usr/bin/env python3
"""Install Dash docsets and search them offline (stdlib only)."""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import List, Mapping, Optional

PROJECT_FILE = ".dash-docset.json"
GITIGNORE_LINES = ["*", "!.gitignore", "!notes/", "!notes/**"]

SUBCOMMANDS = {
    "where": "show the docset store location",
    "sources": "list docset sources",
    "install": "install a docset",
    "update": "update installed docsets",
    "list": "list installed docsets",
    "remove": "remove an installed docset",
    "search": "search a docset's index",
    "show": "show a documentation page",
    "fts": "full-text search a docset",
    "index-text": "build the full-text index",
    "notes": "read or write notes for a docset",
}


class CLIError(Exception):
    """An error that main() prints to stderr and turns into exit code `code`."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


@dataclass
class Store:
    path: str
    source: str
    read_from: List[str]
    project_docsets: Optional[List[str]]


def _home(env):
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def _abs(path, base, env):
    """Absolute, normalised path; ~ expands from env; relative resolves against base."""
    if path == "~" or path.startswith(("~/", "~\\")):
        path = os.path.join(_home(env), path[2:])
    return os.path.normpath(os.path.join(base, path))


def user_config_path(env):
    if sys.platform == "win32" and env.get("APPDATA"):
        base = env["APPDATA"]
    else:
        base = env.get("XDG_CONFIG_HOME") or os.path.join(_home(env), ".config")
    return os.path.join(base, "dash-docset", "config.json")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise CLIError("cannot read %s: %s" % (path, e), 2)
    if not isinstance(data, dict):
        raise CLIError("%s: expected a JSON object" % path, 2)
    return data


def find_project_file(cwd):
    d = os.path.abspath(cwd)
    while True:
        candidate = os.path.join(d, PROJECT_FILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def resolve_store(cli_dir, cwd, env) -> Optional[Store]:
    """--dir > DASH_DOCSET_DIR > project file > user config > None."""
    project_path = find_project_file(cwd)
    project = _load_json(project_path) if project_path else {}
    project_base = os.path.dirname(project_path) if project_path else cwd
    docsets = project.get("docsets") if project_path else None
    user_path = user_config_path(env)
    user = _load_json(user_path) if os.path.isfile(user_path) else {}

    def read_from(cfg, base):
        return [_abs(p, base, env) for p in cfg.get("read_from", [])]

    if cli_dir:
        return Store(_abs(cli_dir, cwd, env), "--dir", [], docsets)
    if env.get("DASH_DOCSET_DIR"):
        return Store(_abs(env["DASH_DOCSET_DIR"], cwd, env), "DASH_DOCSET_DIR", [], docsets)
    if project.get("store"):
        return Store(_abs(project["store"], project_base, env), "project file",
                     read_from(project, project_base), docsets)
    if user.get("store"):
        return Store(_abs(user["store"], os.path.dirname(user_path), env),
                     "user config", read_from(user, os.path.dirname(user_path)), docsets)
    return None


def discover(env) -> List[str]:
    """Existing docset folders of dasht, Zeal and Dash (read-only hints)."""
    home = _home(env)
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    candidates = [
        env.get("DASHT_DOCSETS_DIR"),
        os.path.join(data, "dasht", "docsets"),
        os.path.join(home, ".local", "share", "Zeal", "Zeal", "docsets"),
        os.path.join(env["LOCALAPPDATA"], "Zeal", "Zeal", "docsets")
        if env.get("LOCALAPPDATA") else None,
        os.path.join(home, "Library", "Application Support", "Dash", "DocSets"),
    ]
    found = []
    for c in candidates:
        if c and os.path.isdir(c) and c not in found:
            found.append(c)
    return found


def require_store(args, cwd=None, env=None) -> Store:
    """The resolved store, or CLIError(code 3) listing discovered folders."""
    env = os.environ if env is None else env
    store = resolve_store(getattr(args, "dir", None), cwd or os.getcwd(), env)
    if store is None:
        lines = ["storage location not set",
                 "Set one with: docset.py where --set PATH (--project | --user),",
                 "or --dir PATH, or DASH_DOCSET_DIR."]
        found = discover(env)
        if found:
            lines.append("Existing docset folders found (other tools; read-only "
                         "candidates for --read-from):")
            lines += ["  " + f for f in found]
        raise CLIError("\n".join(lines), 3)
    return store


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def cmd_where(args):
    env, cwd = os.environ, os.getcwd()
    if args.set:
        if args.project == args.user:
            raise CLIError("where --set needs exactly one of --project or --user", 2)
        if args.project:
            target = os.path.join(cwd, PROJECT_FILE)
            base = cwd
        else:
            target = user_config_path(env)
            base = os.path.dirname(target)
        data = _load_json(target) if os.path.isfile(target) else {}
        data["store"] = args.set
        if args.read_from:
            data["read_from"] = list(args.read_from)
        _write_json(target, data)
        store_dir = _abs(args.set, base, env)
        os.makedirs(store_dir, exist_ok=True)
        if (args.project and os.path.basename(store_dir) == ".docsets"
                and os.path.dirname(store_dir) == os.path.normpath(cwd)):
            gi = os.path.join(store_dir, ".gitignore")
            if not os.path.exists(gi):
                with open(gi, "w", encoding="utf-8") as f:
                    f.write("\n".join(GITIGNORE_LINES) + "\n")
        print("wrote %s (store: %s)" % (target, store_dir))
        return 0
    if args.discover:
        found = discover(env)
        print("\n".join(found) if found else "no existing docset folders found")
        return 0
    store = resolve_store(args.dir, cwd, env)
    if store is None:
        print("storage location not set (use where --set PATH --project|--user)")
        return 0
    print("store: %s" % store.path)
    print("source: %s" % store.source)
    for r in store.read_from:
        print("read-from: %s" % r)
    if store.project_docsets is not None:
        print("project docsets: %s" % ", ".join(store.project_docsets))
    return 0


def not_implemented(args):
    print("not implemented: " + args.command, file=sys.stderr)
    return 2


def build_parser():
    parser = argparse.ArgumentParser(prog="docset.py", description=__doc__)
    parser.add_argument("--dir", metavar="PATH",
                        help="use this docset store (overrides DASH_DOCSET_DIR and config)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in SUBCOMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        if name == "where":
            p.add_argument("--discover", action="store_true",
                           help="list existing dasht/Zeal/Dash docset folders")
            p.add_argument("--set", metavar="PATH", help="save PATH as the store")
            p.add_argument("--project", action="store_true",
                           help="with --set: write .dash-docset.json in the current folder")
            p.add_argument("--user", action="store_true",
                           help="with --set: write the user config file")
            p.add_argument("--read-from", metavar="DIR", action="append",
                           help="with --set: extra read-only docset folder (repeatable)")
            p.set_defaults(handler=cmd_where)
            continue
        p.add_argument("args", nargs="*")
        p.set_defaults(handler=not_implemented)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except CLIError as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
