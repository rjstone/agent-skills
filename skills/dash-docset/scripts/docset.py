#!/usr/bin/env python3
"""Install Dash docsets and search them offline (stdlib only)."""
import argparse
import json
import os
import sys
import pathlib
import sqlite3
import tempfile
from dataclasses import dataclass, field
from typing import Iterator, List, Mapping, Optional, Tuple

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


def _try_load(path):
    """(data, None) or ({}, CLIError) so a bad config only matters if it is used."""
    try:
        return _load_json(path), None
    except CLIError as e:
        return {}, e


def resolve_store(cli_dir, cwd, env) -> Optional[Store]:
    """--dir > DASH_DOCSET_DIR > project file > user config > None.

    A malformed config is an error only when it is the one that decides; for
    --dir/DASH_DOCSET_DIR it is ignored (read_from then comes from the project
    config, else the user config, whichever parses)."""
    project_path = find_project_file(cwd)
    project, project_err = _try_load(project_path) if project_path else ({}, None)
    project_base = os.path.dirname(project_path) if project_path else cwd
    docsets = project.get("docsets") if project_path else None
    user_path = user_config_path(env)
    user, user_err = (_try_load(user_path) if os.path.isfile(user_path)
                      else ({}, None))
    user_base = os.path.dirname(user_path)

    def read_from(cfg, base):
        return [_abs(p, base, env) for p in cfg.get("read_from", [])]

    explicit = cli_dir or env.get("DASH_DOCSET_DIR")
    if explicit:
        if "read_from" in project:
            ro = read_from(project, project_base)
        else:
            ro = read_from(user, user_base)
        if cli_dir:
            return Store(_abs(cli_dir, cwd, env), "--dir", ro, docsets)
        return Store(_abs(env["DASH_DOCSET_DIR"], cwd, env), "DASH_DOCSET_DIR",
                     ro, docsets)
    if project_err:
        raise project_err
    if project.get("store"):
        return Store(_abs(project["store"], project_base, env), "project file",
                     read_from(project, project_base), docsets)
    if user_err:
        raise user_err
    if user.get("store"):
        return Store(_abs(user["store"], user_base, env),
                     "user config", read_from(user, user_base), docsets)
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


FULL_SIZE_MIN_ENTRIES = 500


@dataclass
class Docset:
    name: str
    path: str
    foreign: bool
    source: Optional[str]
    version: Optional[str]
    entry_count: int
    clashes: List[str] = field(default_factory=list)  # shadowed foreign copies

    @property
    def full_size(self) -> bool:
        if self.source == "cheat":
            return False
        if (self.foreign or self.source is None) and self.entry_count < FULL_SIZE_MIN_ENTRIES:
            return False
        return True


def meta_dir(store) -> str:
    return os.path.join(store.path, ".dash-docset")


def load_installed(store) -> dict:
    path = os.path.join(meta_dir(store), "installed.json")
    if not os.path.isfile(path):
        return {}
    return _load_json(path)


def save_installed(store, data) -> None:
    d = meta_dir(store)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="installed.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, os.path.join(d, "installed.json"))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def index_path(docset_path) -> str:
    return os.path.join(docset_path, "Contents", "Resources", "docSet.dsidx")


def _open_ro(path):
    uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def count_entries(docset_path) -> int:
    con = _open_ro(index_path(docset_path))
    try:
        tables = _tables(con)
        table = "searchIndex" if "searchIndex" in tables else (
            "ZTOKEN" if "ZTOKEN" in tables else None)
        if table is None:
            raise ValueError("no searchIndex or ZTOKEN table")
        return con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        con.close()


def iter_entries(ds) -> Iterator[Tuple[int, str, str, str]]:
    """Yield (id, name, type, path) from either index form."""
    con = _open_ro(index_path(ds.path))
    try:
        if "searchIndex" in _tables(con):
            sql = "SELECT id, name, type, path FROM searchIndex ORDER BY id"
            for i, n, t, p in con.execute(sql):
                yield i, n, t or "", p or ""
        else:
            sql = ("SELECT k.Z_PK, k.ZTOKENNAME, ty.ZTYPENAME, f.ZPATH, m.ZANCHOR "
                   "FROM ZTOKEN k "
                   "LEFT JOIN ZTOKENTYPE ty ON ty.Z_PK = k.ZTOKENTYPE "
                   "LEFT JOIN ZTOKENMETAINFORMATION m ON m.Z_PK = k.ZMETAINFORMATION "
                   "LEFT JOIN ZFILEPATH f ON f.Z_PK = m.ZFILE ORDER BY k.Z_PK")
            for i, n, t, p, a in con.execute(sql):
                yield i, n, t or "", (p or "") + ("#" + a if a else "")
    finally:
        con.close()


def _docset_dirs(root, depth):
    """*.docset folders directly in root (and one level down when depth=2)."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return
    for n in names:
        full = os.path.join(root, n)
        if n.endswith(".docset"):
            if os.path.isdir(full):
                yield full
        elif depth > 1 and os.path.isdir(full):
            for sub in _docset_dirs(full, depth - 1):
                yield sub


def _warn(msg):
    print("warning: " + msg, file=sys.stderr)


def _make_docset(path, foreign, source, version):
    name = os.path.basename(path)[:-len(".docset")]
    try:
        count = count_entries(path)
    except (sqlite3.Error, OSError, ValueError) as e:
        _warn("skipping unreadable docset %s: %s" % (path, e))
        return None
    return Docset(name, path, foreign, source, version, count)


def find_docsets(store) -> List[Docset]:
    """Docsets of the store (flat), then of each read_from dir (foreign)."""
    installed = load_installed(store)
    result = {}
    for path in _docset_dirs(store.path, 1):
        name = os.path.basename(path)[:-len(".docset")]
        meta = installed.get(name)
        meta = meta if isinstance(meta, dict) else {}
        ds = _make_docset(path, False, meta.get("source"), meta.get("version"))
        if ds:
            result[ds.name] = ds
    for root in store.read_from:
        for path in _docset_dirs(root, 2):
            ds = _make_docset(path, True, None, None)
            if ds is None:
                continue
            if ds.name in result:
                if result[ds.name].foreign:
                    continue  # first read_from copy wins
                result[ds.name].clashes.append(os.path.dirname(path))
                continue
            result[ds.name] = ds
    return list(result.values())


def cmd_list(args):
    store = require_store(args)
    docs = find_docsets(store)
    if not docs:
        print("no docsets found in %s" % store.path)
        return 0
    for d in docs:
        origin = ("foreign (%s)" % os.path.dirname(d.path) if d.foreign
                  else d.source or "unknown")
        line = "%s  %s  %s  %d entries  %s" % (
            d.name, origin, d.version or "-", d.entry_count,
            "full" if d.full_size else "small")
        if d.clashes:
            line += "  (also in %s; store copy used)" % ", ".join(d.clashes)
        print(line)
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
        if name == "list":
            p.set_defaults(handler=cmd_list)
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
