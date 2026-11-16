#!/usr/bin/env python3
"""Install Dash docsets and search them offline (stdlib only)."""
import argparse
import io
import posixpath
import zlib
import json
import os
import sys
import pathlib
import plistlib
import re
import shutil
import sqlite3
import http.client
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit
from dataclasses import dataclass, field
from typing import Iterator, List, Mapping, Optional, Tuple

# Script version. Bump it (and SKILL.md's metadata.version to at least the
# same value) only when this script changes; SKILL.md may run ahead of it.
VERSION = "0.1.0"

PROJECT_FILE = ".dash-docset.json"
GITIGNORE_LINES = ["*", "!.gitignore", "!notes/", "!notes/**"]

SUBCOMMANDS = {
    "where": "show the docset store location",
    "sources": "search the user-contributed docsets (Dash or Zeal downloads them)",
    "list": "list the docsets found and their versions",
    "remove": "remove a docset from the store",
    "search": "search a docset's index",
    "show": "show a documentation page",
    "fts": "full-text search a docset",
    "index-text": "build the full-text index",
    "notes": "print a docset's notes, their path (to edit) or a size check",
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
    note: Optional[str] = None  # set when the project file came from a fallback


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


USERS_FOLDERS = {"home", "users"}  # /home; /Users (macOS); \Users (Windows)


def walk_up(start, env) -> Iterator[str]:
    """start, its parent, and so on, for the fallback searches. The home
    folder is the last one checked; a folder that holds users' homes and a
    filesystem root never are."""
    home = os.path.normpath(_home(env))
    d = os.path.abspath(start)
    while True:
        parent = os.path.dirname(d)
        if parent == d or d == os.path.dirname(home):
            return
        if os.path.dirname(parent) == parent \
                and os.path.basename(d).lower() in USERS_FOLDERS:
            return
        yield d
        if d == home:
            return
        d = parent


def script_dir() -> str:
    """The script's folder as it was invoked (symlinks not resolved)."""
    return os.path.dirname(os.path.abspath(__file__))


def skill_dir() -> str:
    d = script_dir()
    return os.path.dirname(d) if os.path.basename(d) == "scripts" else d


def _is_within(path, folder) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # different drives
        return False


def parent_process_dirs(limit=8) -> List[str]:
    """Working folders of this process's ancestors, nearest first (Linux
    /proc only; elsewhere an empty list). The shell that ran `cd X && python
    ...` is in X, but the program that started that shell usually is still
    in the project folder."""
    out, pid = [], os.getppid()
    for _ in range(limit):
        if pid <= 1:
            break
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if cwd not in out:
            out.append(cwd)
    return out


def fallback_bases(env) -> List[Tuple[str, str]]:
    """[(folder, what it is)] to search upward from when the current folder
    and its parents have no project file."""
    bases = [(script_dir(), "the script's folder")]
    if env.get("OLDPWD"):
        bases.append((env["OLDPWD"], "OLDPWD, the previous folder"))
    bases += [(d, "a parent process's folder") for d in parent_process_dirs()]
    seen, out = set(), []
    for d, what in bases:
        if os.path.isabs(d) and os.path.isdir(d) and d not in seen:
            seen.add(d)
            out.append((d, what))
    return out


def locate_project_file(cwd, env) -> Tuple[Optional[str], Optional[str]]:
    """(project file, None) from the current folder upward, else (file, what
    it was found from) from the fallback folders upward, else (None, None)."""
    path = find_project_file(cwd)
    if path:
        return path, None
    for base, what in fallback_bases(env):
        for d in walk_up(base, env):
            candidate = os.path.join(d, PROJECT_FILE)
            if os.path.isfile(candidate):
                return candidate, what
    return None, None


def _try_load(path):
    """(data, None) or ({}, CLIError) so a bad config only matters if it is used."""
    try:
        return _load_json(path), None
    except CLIError as e:
        return {}, e


def resolve_store(cli_dir, cwd, env) -> Optional[Store]:
    """--dir > DASH_DOCSET_DIR > project file > user config > None.

    The project file is looked for from the current folder upward, then from
    the script's folder, OLDPWD and parent processes' folders upward (see
    locate_project_file); Store.note says so when a fallback found it.

    A malformed config is an error only when it is the one that decides; for
    --dir/DASH_DOCSET_DIR it is ignored (read_from then comes from the project
    config, else the user config, whichever parses)."""
    project_path, found_from = locate_project_file(cwd, env)
    note = found_from and "using %s (found from %s; no %s in or above the " \
        "current folder)" % (project_path, found_from, PROJECT_FILE)
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
                     read_from(project, project_base), docsets, note)
    if user_err:
        raise user_err
    if user.get("store"):
        return Store(_abs(user["store"], user_base, env),
                     "user config", read_from(user, user_base), docsets)
    return None


# Where Zeal keeps docsets (zealdocs/zeal src/libs/core/settings.cpp and
# src/app/main.cpp, checked 2026-11-14): the "docsets/path" setting, else Qt's
# AppLocalDataLocation for organization "Zeal", app "Zeal", plus "/docsets":
#   Linux   $XDG_DATA_HOME/Zeal/Zeal/docsets (~/.local/share/...)
#   macOS   ~/Library/Application Support/Zeal/Zeal/docsets
#   Windows %LOCALAPPDATA%\Zeal\Zeal\docsets
# Settings (Qt QSettings, organization domain zealdocs.org):
#   Linux   $XDG_CONFIG_HOME/Zeal/Zeal.conf, [docsets] path=
#   macOS   ~/Library/Preferences/org.zealdocs.Zeal.plist, key docsets.path
#   Windows registry HKCU\Software\Zeal\Zeal\docsets, value path
#   portable builds: zeal.ini beside zeal.exe; docsets default to ./docsets
# Flatpak keeps both under ~/.var/app/org.zealdocs.Zeal/{data,config}.
# Dash (macOS only): ~/Library/Application Support/Dash/DocSets/<Name>/<Name>.docset.


def _ini_docsets_path(conf) -> Optional[str]:
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    try:
        if cp.read(conf, encoding="utf-8") and cp.has_option("docsets", "path"):
            return cp.get("docsets", "path").strip().strip('"') or None
    except (configparser.Error, OSError, UnicodeDecodeError):
        pass
    return None


def _zeal_custom_paths(env, apps=()) -> List[str]:
    """Docset folders set in Zeal's settings, on any OS, if any."""
    home = _home(env)
    conf_home = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    out = [_ini_docsets_path(c) for c in (
        os.path.join(conf_home, "Zeal", "Zeal.conf"),
        os.path.join(home, ".var", "app", "org.zealdocs.Zeal", "config", "Zeal", "Zeal.conf"))]
    plist = os.path.join(home, "Library", "Preferences", "org.zealdocs.Zeal.plist")
    try:
        with open(plist, "rb") as f:
            data = plistlib.load(f)
        out.append(data.get("docsets.path") or (data.get("docsets") or {}).get("path"))
    except (OSError, ValueError, AttributeError, plistlib.InvalidFileException):
        pass
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zeal\Zeal\docsets") as k:
                out.append(str(winreg.QueryValueEx(k, "path")[0]))
        except OSError:
            pass
    for app, where in apps:  # portable Zeal: zeal.ini beside zeal.exe
        if app == "Zeal" and where.lower().endswith(".exe"):
            app_dir = os.path.dirname(where)
            ini = os.path.join(app_dir, "zeal.ini")
            if os.path.isfile(ini):
                out.append(os.path.join(app_dir, _ini_docsets_path(ini) or "docsets"))
    return [p for p in dict.fromkeys(out) if p]


def viewer_apps(env) -> List[Tuple[str, str]]:
    """Installed Dash or Zeal apps: (app, where found)."""
    home = _home(env)
    found = []
    checks = [("Dash", p) for p in (
        "/Applications/Dash.app", "/Applications/Setapp/Dash.app",
        os.path.join(home, "Applications", "Dash.app"))]
    checks += [("Zeal", p) for p in (
        "/Applications/Zeal.app",
        os.path.join(home, ".var", "app", "org.zealdocs.Zeal"),
        "/var/lib/flatpak/app/org.zealdocs.Zeal")]
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if env.get(var):
            sub = ("Programs", "Zeal") if var == "LOCALAPPDATA" else ("Zeal",)
            checks.append(("Zeal", os.path.join(env[var], *sub, "zeal.exe")))
    for app, path in checks:
        if os.path.exists(path) and app not in [a for a, _ in found]:
            found.append((app, path))
    exe = shutil.which("zeal", path=env.get("PATH"))
    if exe and "Zeal" not in [a for a, _ in found]:
        found.append(("Zeal", exe))
    return found


def discover(env) -> List[str]:
    """Existing docset folders of dasht, Zeal and Dash (read-only hints)."""
    home = _home(env)
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    candidates = [
        env.get("DASHT_DOCSETS_DIR"),
        os.path.join(data, "dasht", "docsets"),
        *_zeal_custom_paths(env, viewer_apps(env)),
        os.path.join(data, "Zeal", "Zeal", "docsets"),
        os.path.join(home, ".local", "share", "Zeal", "Zeal", "docsets"),
        os.path.join(home, ".var", "app", "org.zealdocs.Zeal", "data", "Zeal", "Zeal",
                     "docsets"),
        os.path.join(home, "Library", "Application Support", "Zeal", "Zeal", "docsets"),
        os.path.join(env["LOCALAPPDATA"], "Zeal", "Zeal", "docsets")
        if env.get("LOCALAPPDATA") else None,
        os.path.join(home, "Library", "Application Support", "Dash", "DocSets"),
    ]
    found = []
    for c in candidates:
        if c and os.path.isdir(c) and c not in found:
            found.append(c)
    return found


def looked_in(cwd, env) -> str:
    """One line for the 'not set' messages: where a config was looked for."""
    folders = [cwd] + [d for d, _ in fallback_bases(env) if d != cwd]
    return ("Looked for %s in and above: %s; and for %s. A project's file is "
            "found from the project folder: run the script there, by its full "
            "path." % (PROJECT_FILE, "; ".join(folders), user_config_path(env)))


def require_store(args, cwd=None, env=None) -> Store:
    """The resolved store, or CLIError(code 3) listing discovered folders."""
    env = os.environ if env is None else env
    cwd = cwd or os.getcwd()
    store = resolve_store(getattr(args, "dir", None), cwd, env)
    if store is not None and store.note:
        print("note: " + store.note, file=sys.stderr)
    if store is None:
        lines = ["storage location not set",
                 "Set one with: docset.py where --set PATH (--project | --user),",
                 "or --dir PATH, or DASH_DOCSET_DIR.",
                 "Agents: first read references/setup.md in the skill folder; "
                 "the user chooses the location.",
                 looked_in(cwd, env)]
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


def _refuse_other_store(args, target, base, data, env):
    """where --set without --replace: stop before a store that is already
    set gets swapped for another one (its docsets would drop out of use)."""
    new = _abs(args.set, base, env)
    if data.get("store"):
        old, where = _abs(data["store"], base, env), target
    elif args.project and not os.path.isfile(target):
        above = find_project_file(base)
        cfg = _try_load(above)[0] if above else {}
        if not cfg.get("store"):
            return
        old, where = _abs(cfg["store"], os.path.dirname(above), env), above
    else:
        return
    if old == new:
        return
    raise CLIError(
        "%s already sets the store to %s. Nothing was changed. To keep using "
        "that store, just run the commands. To switch to "
        "%s anyway, add --replace%s." % (
            where, old, new,
            "" if where == target else " (the new file would hide that one)"), 2)


def cmd_where(args):
    env, cwd = os.environ, os.getcwd()
    if args.set:
        if args.project == args.user:
            raise CLIError("where --set needs exactly one of --project or --user", 2)
        if args.project:
            base = cwd
            if _is_within(cwd, skill_dir()):
                # `cd <skill folder> && python scripts/docset.py ...`: the
                # project is the folder the shell came from, not the skill's
                base = env.get("OLDPWD")
                if not base or not os.path.isdir(base) or _is_within(base, skill_dir()):
                    raise CLIError(
                        "where --set --project: the current folder is inside the "
                        "skill folder, so it is not the project. Run this from "
                        "the project folder, giving the script's full path.", 2)
                print("note: the current folder is inside the skill folder; "
                      "writing the project file in %s (OLDPWD)" % base, file=sys.stderr)
            target = os.path.join(base, PROJECT_FILE)
        else:
            target = user_config_path(env)
            base = os.path.dirname(target)
        data = _load_json(target) if os.path.isfile(target) else {}
        if not args.replace:
            _refuse_other_store(args, target, base, data, env)
        data["store"] = args.set
        if args.read_from:
            data["read_from"] = list(args.read_from)
        _write_json(target, data)
        store_dir = _abs(args.set, base, env)
        os.makedirs(store_dir, exist_ok=True)
        if (args.project and os.path.basename(store_dir) == ".docsets"
                and os.path.dirname(store_dir) == os.path.normpath(base)):
            gi = os.path.join(store_dir, ".gitignore")
            if not os.path.exists(gi):
                with open(gi, "w", encoding="utf-8") as f:
                    f.write("\n".join(GITIGNORE_LINES) + "\n")
        print("wrote %s (store: %s)" % (target, store_dir))
        return 0
    if args.discover:
        current = resolve_store(args.dir, cwd, env)
        print("store: %s (%s)" % (current.path, current.source) if current
              else "store: not set")
        apps = viewer_apps(env)
        for app, where in apps:
            print("app: %s (%s)" % (app, where))
        if not apps:
            print("no Dash or Zeal installation found")
        found = discover(env)
        for d in found:
            print("docsets: %s" % d)
        if not found:
            print("no existing docset folders found")
        return 0
    store = resolve_store(args.dir, cwd, env)
    if store is None:
        print("storage location not set (use where --set PATH --project|--user)\n"
              "Agents: first read references/setup.md in the skill folder; "
              "the user chooses the location.\n" + looked_in(cwd, env))
        return 3
    if store.note:
        print("note: " + store.note, file=sys.stderr)
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


def like_pattern(query) -> str:
    """dasht's fuzzy pattern %a%b%c% with %, _ and \\ escaped (ESCAPE '\\')."""
    esc = ["\\" + c if c in "%_\\" else c for c in query]
    return "%" + "%".join(esc) + "%"


def iter_entries(ds, like: Optional[str] = None,
                 entry_id: Optional[int] = None) -> Iterator[Tuple[int, str, str, str]]:
    """Yield (id, name, type, path) from either index form.

    like: optional SQL LIKE pattern (ESCAPE '\\') the name must match.
    entry_id: optional id; only that entry is read (a keyed lookup)."""
    con = _open_ro(index_path(ds.path))
    try:
        has_search_index = "searchIndex" in _tables(con)
        if has_search_index:
            sql = "SELECT id, name, type, path FROM searchIndex"
            id_col, name_col = "id", "name"
        else:
            sql = ("SELECT k.Z_PK, k.ZTOKENNAME, ty.ZTYPENAME, f.ZPATH, m.ZANCHOR "
                   "FROM ZTOKEN k "
                   "LEFT JOIN ZTOKENTYPE ty ON ty.Z_PK = k.ZTOKENTYPE "
                   "LEFT JOIN ZTOKENMETAINFORMATION m ON m.Z_PK = k.ZMETAINFORMATION "
                   "LEFT JOIN ZFILEPATH f ON f.Z_PK = m.ZFILE")
            id_col, name_col = "k.Z_PK", "k.ZTOKENNAME"
        where, params = [], []
        if like is not None:
            where.append("%s LIKE ? ESCAPE '\\'" % name_col)
            params.append(like)
        if entry_id is not None:
            where.append("%s = ?" % id_col)
            params.append(entry_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY " + id_col
        if has_search_index:
            for i, n, t, p in con.execute(sql, params):
                yield i, n, t or "", p or ""
        else:
            for i, n, t, p, a in con.execute(sql, params):
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


class ScopeError(CLIError):
    def __init__(self, message):
        super().__init__(message, 4)


MAX_FULL_UNSCOPED = 4


def parse_ref(ref: str) -> Tuple[str, int]:
    """'<DocsetName>:<id>' -> (name, id); the id follows the last colon."""
    name, sep, num = ref.rpartition(":")
    if not sep or not name or not (num.isascii() and num.isdecimal()):
        raise CLIError("bad reference %r (expected <Docset>:<id>)" % ref, 2)
    return name, int(num)


def rank(query: str, name: str) -> Optional[int]:
    """0 exact, 1 prefix, 2 substring, 3 fuzzy (in order), None no match."""
    q, n = query.lower(), name.lower()
    if n == q:
        return 0
    if n.startswith(q):
        return 1
    if q in n:
        return 2
    pos = 0
    for c in q:
        pos = n.find(c, pos) + 1
        if pos == 0:
            return None
    return 3


def pick_docset(docsets, name, error=None) -> Docset:
    """The docset with this name; if none has exactly it, the only one that
    differs just in letter case (-d pandas finds Pandas)."""
    error = error or (lambda msg: CLIError(msg, 5))
    exact = next((d for d in docsets if d.name == name), None)
    if exact:
        return exact
    close = [d for d in docsets if d.name.lower() == name.lower()]
    if len(close) == 1:
        return close[0]
    if close:
        raise error("docset %r: %s differ only in letter case; give the exact "
                    "name" % (name, " and ".join(d.name for d in close)))
    raise error("unknown docset %r (see: docset.py list)" % name)


def select_docsets(store, all_docsets, names, use_all) -> List[Docset]:
    """Scope: -d names > project list > all if <= 4 full-size or use_all."""
    wanted = names or store.project_docsets
    if wanted:
        picked = []
        for n in wanted:
            d = pick_docset(all_docsets, n, ScopeError)
            if d not in picked:
                picked.append(d)
        return picked
    full = [d for d in all_docsets if d.full_size]
    if use_all or len(full) <= MAX_FULL_UNSCOPED:
        return list(all_docsets)
    raise ScopeError(
        "%d full-size docsets and no scope; searching all of them is slow and "
        "noisy.\nFull-size docsets: %s\nNarrow it with -d NAME (repeatable), "
        "a \"docsets\" list in %s, or search everything with --all."
        % (len(full), ", ".join(d.name for d in full), PROJECT_FILE))


def cap_lines(lines, max_lines, hint) -> List[str]:
    if len(lines) <= max_lines:
        return list(lines)
    cut = len(lines) - max_lines
    return list(lines[:max_lines]) + ["... %d more lines cut; %s" % (cut, hint)]


FUZZY_SHOWN = 0  # fuzzy hits shown when exact, prefix or substring hits exist


def _join_query(args):
    """QUERY may be given as several words; join them with single spaces."""
    q = args.query
    args.query = " ".join(q).strip() if isinstance(q, list) else (q or "")


def _fold_bare_entries(hits, no_anchor, page_of):
    """Drop a whole-page entry when an anchored entry with the same short name
    on the same page is also a hit: `show` opens the same section for both
    (it starts a bare entry at the heading named like it). Returns the kept
    hits and {(docset, id): [folded REFs]}; nothing is lost, the REF moves."""
    twin = {}  # (docset, page, short name) -> first anchored hit
    for h in hits:
        key = (h[3], h[4])
        if key in page_of and key not in no_anchor:
            twin.setdefault((h[3], page_of[key], _short_name(h[2])), key)
    kept, also = [], {}
    for h in hits:
        key = (h[3], h[4])
        target = (twin.get((h[3], page_of[key], _short_name(h[2])))
                  if key in no_anchor else None)
        if target is not None:
            also.setdefault(target, []).append("%s:%d" % key)
        else:
            kept.append(h)
    return kept, also


def _best_per_word(docs, words, want_type) -> List[Tuple[str, Optional[str]]]:
    """[(word, 'REF  type  name' of its best non-fuzzy entry, or None)], for
    a query whose words are never all in one name (several names at once)."""
    out = []
    for w in dict.fromkeys(words):
        best = None
        for ds in docs:
            try:
                for i, name, typ, path in iter_entries(ds, like_pattern(w)):
                    if want_type is not None and typ.lower() != want_type:
                        continue
                    r = rank(w, name)
                    if r is not None and _short_name(name) == w:
                        r = 0
                    if r is None or r >= 3:
                        continue
                    bare = entry_location(path)[1] is None
                    key = (r, bare, len(name), name, ds.name, i)
                    if best is None or key < best[0]:
                        best = (key, "%s:%d  %s  %s" % (ds.name, i, typ, name))
            except sqlite3.Error:
                pass
        out.append((w, best and best[1]))
    return out


def cmd_search(args):
    _join_query(args)
    if not args.query:
        raise CLIError("empty search query", 2)
    store = require_store(args)
    docs = select_docsets(store, find_docsets(store), args.docset or [], args.all)
    words = args.query.lower().split()
    # several words: prefilter on the longest; a name holding all of them in
    # any order ranks like a substring hit (2)
    like = like_pattern(max(words, key=len) if len(words) > 1 else args.query)
    want_type = args.type.lower() if args.type else None
    hits = []
    no_anchor = set()  # (docset, id) of entries that point at a whole page
    page_of = {}  # (docset, id) -> page file
    q_lower = args.query.lower()
    for ds in docs:
        try:
            for i, name, typ, path in iter_entries(ds, like):
                if want_type is not None and typ.lower() != want_type:
                    continue
                r = rank(args.query, name)
                if r and _short_name(name) == q_lower:
                    r = 0  # 'f(a, b)' for query 'f' is an exact match
                if not re.match(r"https?://", path, re.I):
                    file_part, anchor = entry_location(path)
                    page_of[(ds.name, i)] = file_part
                    if anchor is None:
                        no_anchor.add((ds.name, i))
                if (r is None or r == 3) and len(words) > 1 \
                        and all(w in name.lower() for w in words):
                    r = 2
                if r is not None:
                    hits.append((r, len(name), name, ds.name, i, typ))
        except sqlite3.Error as e:
            _warn("skipping %s: %s" % (ds.name, e))
    # within a rank, entries with an anchor (a section) before whole pages
    hits.sort(key=lambda h: (h[0], (h[3], h[4]) in no_anchor) + h[1:5])
    hits, also = _fold_bare_entries(hits, no_anchor, page_of)
    hint = "raise --max-lines or narrow the query, -d or --type"
    if args.json:
        items = []
        for r, _l, n, d, i, t in hits[:args.max_lines]:
            item = {"ref": "%s:%d" % (d, i), "docset": d, "type": t, "name": n,
                    "rank": r}
            if (d, i) in also:
                item["same_section"] = also[(d, i)]
            items.append(item)
        print(json.dumps(items, indent=2))
        return 0
    real = sum(1 for h in hits if h[0] < 3)
    if real and len(hits) - real > FUZZY_SHOWN:
        cut = len(hits) - real - FUZZY_SHOWN
        hits = hits[:real + FUZZY_SHOWN]
    else:
        cut = 0
    lines = []
    for k, (r, _l, n, d, i, t) in enumerate(hits):
        if r == 3 and (k == 0 or hits[k - 1][0] < 3):
            lines.append("no exact, prefix or substring matches; fuzzy matches "
                         "(letters in order, often unrelated):" if k == 0 else
                         "--- fuzzy matches (letters in order, often unrelated) ---")
        lines.append("%s:%d  %s  %s" % (d, i, t, n))
    # silent when a hit holds the query as whole words (asyncio.gather for
    # "gather"): nobody needs the fuzzy ones then
    whole = re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % r"[\W_]+".join(
        re.escape(w) for w in words), re.I)
    if cut and not any(h[0] < 3 and whole.search(h[2]) for h in hits):
        lines.append("... %d fuzzy matches hidden (letters in order only, often "
                     "unrelated)" % cut)
    if not hits:
        each = _best_per_word(docs, words, want_type) if len(words) > 1 else []
        if any(best for _w, best in each):
            lines.append("no matches for %r: search wants all the words in one "
                         "entry name. Best entry for each word:" % args.query)
            for w, best in each:
                lines.append(best or "(no entry name contains %r; fts searches "
                                     "the text inside pages)" % w)
        else:
            lines.append("no matches for %r (entry names only; fts searches the "
                         "text inside pages)" % args.query)
    for line in cap_lines(lines, args.max_lines, hint):
        print(line)
    return 0


@dataclass
class Block:
    level: int        # heading level 1-6, 0 for other blocks
    ids: List[str]    # ids / <a name> seen since the last emitted block
    text: str         # one or more lines
    tag: str          # element that started the block (the id carrier if any)
    depth: int        # open dl/table/ul/ol containers


SKIP_TAGS = {"script", "style", "nav", "header", "footer", "form", "select",
             "noscript", "template"}
SKIP_ROLES = {"navigation", "search", "banner", "contentinfo"}
# Navigation chrome of common doc generators (Sphinx, Read the Docs, ...);
# "headerlink" (Sphinx) and "copiable-link" (GNU Texinfo) are pilcrow links.
SKIP_CLASSES = {"related", "mobile-nav", "sphinxsidebar", "sphinxsidebarwrapper",
                "breadcrumbs", "breadcrumb", "wy-nav-side", "rst-versions",
                "headerlink", "copiable-link", "toc-drawer", "sidebar-drawer",
                "skip-link"}


def _skippable(tag, a) -> bool:
    return (tag in SKIP_TAGS or a.get("role") in SKIP_ROLES
            or bool(SKIP_CLASSES.intersection((a.get("class") or "").split())))
CONTAINER_TAGS = {"dl", "table", "ul", "ol"}
BLOCK_TAGS = {"p", "div", "li", "dt", "dd", "tr", "pre", "ul", "ol", "dl", "table",
              "section", "article", "blockquote", "caption", "details", "summary",
              "figure", "figcaption", "body", "main", "aside", "address", "form",
              "fieldset", "hr", "h1", "h2", "h3", "h4", "h5", "h6"}
HEADINGS = {"h%d" % i: i for i in range(1, 7)}
CLOSES_SAME = {"li": ("li",), "dt": ("dt", "dd"), "dd": ("dt", "dd"), "p": ("p",),
               "tr": ("tr",)}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[Block] = []
        self.buf: List[str] = []
        self.stack: List[str] = []
        self.skip = 0
        self.in_pre = False
        self.depth = 0
        self.level = 0
        self.prefix = ""
        self.ids: List[str] = []
        self.id_tag = ""
        self.start_depth = 0
        self.skip_tag = ""
        self.cell = None  # (buf index, colspan) of the open table cell

    def _top(self):
        return self.stack[-1] if self.stack else ""

    def flush(self):
        self._end_cell()
        raw = "".join(self.buf)
        self.buf = []
        if self.in_pre:
            text = raw.strip("\n").rstrip()
            text = "```\n" + text + "\n```" if text.strip() else ""
        else:
            text = " ".join(raw.split())
        if not text:
            self.level = 0
            if self.prefix != "- ":
                self.prefix = ""
            return
        if self.level:
            tag = "h%d" % self.level
            text = "#" * self.level + " " + text
        else:
            tag = self.id_tag or self._top()
            text = self.prefix + text
        self.blocks.append(Block(self.level, self.ids, text, tag, self.start_depth))
        self.ids, self.id_tag, self.level, self.prefix = [], "", 0, ""

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip_tag:
                self.skip += 1
            return
        a = dict(attrs)
        if _skippable(tag, a):
            if tag in BLOCK_TAGS or tag in SKIP_TAGS:
                self.flush()
            self.skip, self.skip_tag = 1, tag
            return
        if tag in BLOCK_TAGS:
            self.flush()
            if self.stack and self.stack[-1] in CLOSES_SAME.get(tag, ()):
                self.stack.pop()
            if tag in CONTAINER_TAGS:
                self.depth += 1
            self.stack.append(tag)
            self.start_depth = self.depth
            if tag in HEADINGS:
                self.level = HEADINGS[tag]
            elif tag == "li":
                self.prefix = "- "
            elif tag == "pre":
                self.in_pre = True
        elif tag in ("td", "th") and not self.in_pre:
            self._end_cell()
            if self.buf:
                self.buf.append(" | ")
            try:
                span = int(a.get("colspan") or 1)
            except ValueError:
                span = 1
            self.cell = (len(self.buf), span)
        elif tag == "br":
            self.buf.append("\n" if self.in_pre else " ")
        if a.get("id") and tag not in ("link", "meta"):
            self.ids.append(a["id"])
            if tag in BLOCK_TAGS and not self.id_tag:
                self.id_tag = tag
        if tag == "a" and a.get("name"):
            self.ids.append(a["name"])
        if not self.buf:
            self.start_depth = self.depth

    def _end_cell(self):
        """Label a non-empty cell spanning several columns: 'Rm (5 cols)'."""
        if self.cell:
            start, span = self.cell
            self.cell = None
            if span > 1 and "".join(self.buf[start:]).strip():
                self.buf.append(" (%d cols)" % span)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip_tag:
                self.skip -= 1
            return
        if tag in ("td", "th"):
            self._end_cell()
        if tag in BLOCK_TAGS:
            self.flush()
            self.in_pre = self.in_pre and tag != "pre"
            if tag in self.stack:
                while self.stack.pop() != tag:
                    pass
            if tag in CONTAINER_TAGS and self.depth:
                self.depth -= 1
            self.start_depth = self.depth

    def handle_data(self, data):
        if self.skip:
            return
        if not self.buf:
            self.start_depth = self.depth
        self.buf.append(data)

    def close(self):
        super().close()
        self.flush()


def html_to_text(html: str) -> List[Block]:
    """Page HTML -> blocks (headings as '#' lines, <pre> fenced, items as '- ')."""
    p = _TextParser()
    p.feed(html)
    p.close()
    return p.blocks


def entry_location(path: str) -> Tuple[str, Optional[str]]:
    """Index path -> (page file, anchor or None): marker tags dropped, file decoded."""
    path = re.sub(r"<dash_entry_[^>]*>", "", path)
    file_part, sep, anchor = path.partition("#")
    return unquote(file_part), (anchor if sep and anchor else None)


DEFINITION_MAX_LINES = 40  # show --grep adds a matching term's definition up to this


def definition_ends(blocks: List[Block], offset=0) -> dict:
    """{line index of a definition term (<dt>): index after the last line of
    its definition}: the blocks up to the next term at its level or the end
    of its list. Line indexes count from `offset`."""
    starts, n = [], offset
    for b in blocks:
        starts.append(n)
        n += b.text.count("\n") + 1
    starts.append(n)
    ends = {}
    for i, b in enumerate(blocks):
        if b.tag != "dt" or b.level:
            continue
        j = i + 1
        while j < len(blocks) and not blocks[j].level and blocks[j].depth >= b.depth \
                and not (blocks[j].tag == "dt" and blocks[j].depth <= b.depth):
            j += 1
        if j > i + 1:
            for ln in range(starts[i], starts[i + 1]):
                ends[ln] = starts[j]
    return ends


def section_lines(blocks: List[Block], anchor: Optional[str]) -> Tuple[List[str], dict]:
    """(lines of the section the anchor names, definition_ends for them);
    the whole page if there is no anchor or it isn't found."""
    def lines_of(bs):
        return [ln for b in bs for ln in b.text.split("\n")]

    if not anchor:
        return lines_of(blocks), definition_ends(blocks)
    want = {anchor, unquote(anchor)}
    start = None
    for i, b in enumerate(blocks):
        if any(x in want or unquote(x) in want for x in b.ids):
            start = i
            break
    if start is None:
        return (["note: anchor not found (%s); showing the whole page" % anchor]
                + lines_of(blocks), definition_ends(blocks, 1))
    first = blocks[start]
    end = len(blocks)
    for j in range(start + 1, len(blocks)):
        b = blocks[j]
        if first.level:
            stop = b.level and b.level <= first.level
        else:
            stop = (b.level or b.depth < first.depth
                    or (b.tag == first.tag and b.ids and b.depth <= first.depth))
        if stop:
            end = j
            break
    return lines_of(blocks[start:end]), definition_ends(blocks[start:end])


def trim_to_anchor(blocks: List[Block], anchor: Optional[str]) -> List[str]:
    """Lines of the section the anchor names; whole page if none or not found."""
    return section_lines(blocks, anchor)[0]


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError("%r: must be an integer >= 1" % text)
    return n


def parse_page_ref(ref: str) -> Optional[Tuple[str, str]]:
    """'<Docset>:page:<path>[#anchor]' -> (name, path[#anchor]), else None."""
    name, sep, path = ref.partition(":page:")
    if not sep or not name or not path:
        return None
    return name, path


def page_file(ds, file_part) -> str:
    """Absolute path of a page file inside the docset's Documents; CLIError 5."""
    docs = os.path.join(ds.path, "Contents", "Resources", "Documents")
    page = os.path.normpath(os.path.join(docs, *file_part.split("/")))
    try:
        inside = os.path.commonpath([docs, page]) == docs
    except ValueError:
        inside = False
    if not inside or not os.path.isfile(page):
        raise CLIError("page file not found: %s" % page, 5)
    return page


# Tarix docsets (Dash's compact storage; read by Zeal's tarixarchive.cpp):
# Contents/Resources/tarix.tgz is a normal .tgz written with a zlib full flush
# before every tar record, and tarixIndex.db is SQLite with
# tarindex(path TEXT PRIMARY KEY COLLATE NOCASE, hash TEXT), where path starts
# "<Name>.docset/" and hash is "<block> <offset> <length>": the compressed
# byte offset of a flush point and the record size in 512-byte blocks. Pages
# are read one at a time without unpacking. (Kapeli serves the index as
# <archive>.tgz.tarix: a .tgz holding that SQLite file.)
TARIX_MAX_RECORD = 64 * 1024 * 1024
_TARIX: dict = {}  # Resources dir -> (connection, root prefix) or None


def _tarix(res):
    if res not in _TARIX:
        _TARIX[res] = None
        arc, idx = os.path.join(res, "tarix.tgz"), os.path.join(res, "tarixIndex.db")
        if os.path.isfile(arc) and os.path.isfile(idx):
            try:
                con = _open_ro(idx)
                row = con.execute("SELECT path FROM tarindex WHERE path LIKE "
                                  "'%.docset/%' LIMIT 1").fetchone()
                prefix = row[0][:row[0].index(".docset/") + len(".docset/")] if row else ""
                _TARIX[res] = (con, prefix)
            except (sqlite3.Error, ValueError) as e:
                _warn("unreadable tarix index %s: %s" % (idx, e))
    return _TARIX[res]


def read_tarix(res, rel) -> Optional[bytes]:
    """File rel (e.g. Contents/Resources/Documents/x.html) from the tarix
    archive in the Resources dir res; None if the docset has no archive."""
    t = _tarix(res)
    if t is None:
        return None
    con, prefix = t
    try:
        row = con.execute("SELECT hash FROM tarindex WHERE path = ?", (prefix + rel,)).fetchone()
    except sqlite3.Error as e:
        raise CLIError("tarix index error for %s: %s" % (rel, e), 7)
    if not row or not row[0]:
        raise CLIError("page not in the docset's archive: %s" % rel, 5)
    try:
        _block, offset, blocks = (int(x) for x in str(row[0]).split())
    except ValueError:
        raise CLIError("bad tarix index entry for %s" % rel, 7)
    want = blocks * 512
    if offset < 0 or blocks < 1 or want > TARIX_MAX_RECORD:
        raise CLIError("bad tarix index entry for %s" % rel, 7)
    out = bytearray()
    try:
        with open(os.path.join(res, "tarix.tgz"), "rb") as f:
            f.seek(offset)
            z = zlib.decompressobj(-zlib.MAX_WBITS)
            buf = b""
            while len(out) < want and not z.eof:
                if not buf:
                    buf = f.read(1 << 16)
                    if not buf:
                        break
                out += z.decompress(buf, want - len(out))
                buf = z.unconsumed_tail
        with tarfile.open(fileobj=io.BytesIO(bytes(out[:want])), mode="r:") as tar:
            member = tar.next()
            if member is None or not member.isfile():
                raise CLIError("no file record for %s in the archive" % rel, 7)
            return tar.extractfile(member).read()
    except (OSError, zlib.error, tarfile.TarError) as e:
        raise CLIError("cannot read %s from the docset's archive: %s" % (rel, e), 7)


def read_page_bytes(ds, file_part) -> bytes:
    """A page from Documents/, else from the docset's tarix archive."""
    try:
        with open(page_file(ds, file_part), "rb") as f:
            return f.read()
    except CLIError:
        rel = posixpath.normpath(file_part.replace("\\", "/")).lstrip("/")
        if rel.startswith(".."):
            raise
        data = read_tarix(os.path.join(ds.path, "Contents", "Resources"),
                          "Contents/Resources/Documents/" + rel)
        if data is None:
            raise
        return data


def read_page_blocks(ds, file_part) -> List[Block]:
    return html_to_text(read_page_bytes(ds, file_part).decode("utf-8", errors="replace"))


# A repeated footer is a run of trailing blocks that most pages end with
# exactly (copyright, links to the same few pages, a generator line). Only an
# exact repeat counts, so real docs are never guessed away. It is kept on one
# page (the docset's index page, else the first entry's page) and stripped
# from every other page, for show and for the full-text index.
FOOTER_SAMPLE = 40      # pages sampled, evenly spaced
FOOTER_MIN_PAGES = 5    # fewer pages: no footer detection
FOOTER_SHARE = 0.6      # share of sampled pages that must end with it
FOOTER_MAX_BLOCKS = 30


def _entry_pages(ds) -> List[str]:
    """Page files the entries point at, in entry-id order, without repeats."""
    pages = {}
    for _i, _n, _t, path in iter_entries(ds):
        if not re.match(r"https?://", path, re.I):
            file_part, _a = entry_location(path)
            if file_part:
                pages.setdefault(file_part, None)
    return list(pages)


def _index_page(ds) -> Optional[str]:
    try:
        with open(os.path.join(ds.path, "Contents", "Info.plist"), "rb") as f:
            value = plistlib.load(f).get("dashIndexFilePath")
    except (OSError, ValueError, AttributeError, plistlib.InvalidFileException):
        return None
    return entry_location(value)[0] if isinstance(value, str) and value else None


def detect_footer(ds) -> Tuple[List[str], Optional[str]]:
    """(footer block texts, the page that keeps it); ([], None) if none."""
    pages = _entry_pages(ds)
    if len(pages) < FOOTER_MIN_PAGES:
        return [], None
    step = max(1, len(pages) // FOOTER_SAMPLE)
    counts: dict = {}
    sampled = 0
    for file_part in pages[::step][:FOOTER_SAMPLE]:
        try:
            texts = [b.text for b in read_page_blocks(ds, file_part)]
        except (CLIError, OSError):
            continue
        sampled += 1
        for k in range(1, min(FOOTER_MAX_BLOCKS, len(texts) - 1) + 1):
            key = tuple(texts[-k:])
            counts[key] = counts.get(key, 0) + 1
    need = max(FOOTER_MIN_PAGES, FOOTER_SHARE * sampled)
    if sampled < FOOTER_MIN_PAGES:
        return [], None
    best = max((k for k, c in counts.items() if c >= need), key=len, default=())
    if not best:
        return [], None
    index = _index_page(ds)
    return list(best), (index if index in pages else pages[0])


def footer_info(store, ds) -> Tuple[List[str], Optional[str]]:
    """detect_footer, cached per docset version in the store."""
    cache = os.path.join(meta_dir(store), "footers", ds.name + ".json")
    stamp = docset_stamp(ds)
    try:
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("stamp") == stamp:
            return data.get("footer") or [], data.get("keep")
    except (OSError, ValueError):
        pass
    footer, keep = detect_footer(ds)
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "footer": footer, "keep": keep}, f)
    except OSError:
        pass
    return footer, keep


def page_blocks(store, ds, file_part) -> List[Block]:
    """A page's blocks without the docset's repeated footer (kept on one page)."""
    blocks = read_page_blocks(ds, file_part)
    footer, keep = footer_info(store, ds)
    n = len(footer)
    if n and file_part != keep and len(blocks) > n \
            and [b.text for b in blocks[-n:]] == footer:
        return blocks[:-n]
    return blocks


def _is_table_row(line) -> bool:
    """Table rows render as cells joined by ' | '."""
    return " | " in line or line.lstrip().startswith("|")


def grep_lines(lines, patterns, def_ends=None) -> List[str]:
    """Lines containing any pattern (case-insensitive), plus the nearest
    heading above each, for a table row its table's first row (the header),
    and for a definition term its definition when def_ends (see
    definition_ends) gives one of at most DEFINITION_MAX_LINES lines. Runs of
    skipped lines become '...'."""
    pats = [p.lower() for p in patterns]
    keep = set()
    for i, line in enumerate(lines):
        if not any(p in line.lower() for p in pats):
            continue
        keep.add(i)
        end = (def_ends or {}).get(i)
        if end is not None and end - i - 1 <= DEFINITION_MAX_LINES:
            keep.update(range(i + 1, end))
        head = next((j for j in range(i - 1, -1, -1) if lines[j].startswith("#")), None)
        if head is not None:
            keep.add(head)
        if _is_table_row(line):
            j = i
            while j > 0 and _is_table_row(lines[j - 1]):
                j -= 1
            keep.add(j)
    out, prev = [], -1
    for i in sorted(keep):
        if i != prev + 1:
            out.append("...")
        out.append(lines[i])
        prev = i
    if keep and prev != len(lines) - 1:
        out.append("...")
    return out


def page_title(blocks) -> Optional[str]:
    """The page's top heading (first h1, else first heading), without #s."""
    heads = [b for b in blocks if b.level]
    if not heads:
        return None
    top = min(b.level for b in heads)
    return next(b.text for b in heads if b.level == top).lstrip("#").strip() or None


def _print_page_title(blocks, lines):
    """'(page: Title)' when the section's heading isn't the page's own, so a
    generic heading like '## Parameters' says what it belongs to."""
    title = page_title(blocks)
    if title and lines and lines[0].startswith("#") \
            and lines[0].lstrip("#").strip() != title:
        print("(page: %s)" % title)


def _print_lines(lines, args, def_ends=None):
    footer = None
    if getattr(args, "grep", None):
        total = len(lines)
        wanted = " or ".join(repr(g) for g in args.grep)
        hits = [i for i, l in enumerate(lines)
                if any(g.lower() in l.lower() for g in args.grep)]
        matched = len(hits)
        with_def = any((def_ends or {}).get(i, i + 1) - i - 1 in
                       range(1, DEFINITION_MAX_LINES + 1) for i in hits)
        lines = grep_lines(lines, args.grep, def_ends)
        if not lines:
            print("no lines match %s in this section (%d lines); drop --grep to "
                  "see it" % (wanted, total))
            return
        footer = ("(all %d lines containing %s are shown; the section has %d lines)"
                  % (matched, wanted, total))
        if with_def:
            footer = footer[:-1] + "; a matching term is shown with its definition)"
    if not args.full:
        lines = cap_lines(lines, args.max_lines,
                          "raise --max-lines or use --full for the whole section")
    for line in lines:
        print(line)
    if footer:
        print(footer)


def cmd_show(args):
    page_ref = parse_page_ref(args.ref)
    name, entry_id = page_ref if page_ref else parse_ref(args.ref)
    store = require_store(args)
    ds = pick_docset(find_docsets(store), name)
    name = ds.name
    if page_ref:
        file_part, sep, anchor = entry_id.partition("#")
        blocks = page_blocks(store, ds, file_part)
        lines, def_ends = section_lines(blocks, anchor if sep and anchor else None)
        _print_page_title(blocks, lines)
        _print_lines(lines, args, def_ends)
        if not args.no_notes:
            for line in general_notes(store, name):
                print(line)
        return 0
    entry = next(iter_entries(ds, entry_id=entry_id), None)
    if entry is None:
        raise CLIError("no entry %s in docset %s" % (args.ref, name), 5)
    _id, entry_name, entry_type, path = entry
    if re.match(r"https?://", path, re.I):
        print("online-only entry: " + path)
        return 0
    file_part, anchor = entry_location(path)
    blocks = page_blocks(store, ds, file_part)
    if anchor is None:  # no anchor: start at a heading named like the entry
        want = _short_name(entry_name)
        anchor = next((b.ids[0] for b in blocks if b.level and b.ids
                       and _short_name(b.text.lstrip("#").strip()) == want), None)
    lines, def_ends = section_lines(blocks, anchor)
    _print_page_title(blocks, lines)
    _print_lines(lines, args, def_ends)
    if not args.no_notes:
        for line in notes_for(store, name, entry_name, entry_type):
            print(line)
        _p, text = _read_notes(store, name)
        for w in size_warnings(text or ""):
            print("warning: notes: " + w, file=sys.stderr)
    return 0


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


NOTES_GENERAL_MAX = 50
NOTES_SECTION_MAX = 100
NOTES_TOTAL_MAX = 2000
_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_TYPED = re.compile(r"^(.*?)\s+\(([^()]+)\)$")  # needs a space and a type


def notes_path(store, docset_name) -> str:
    """Notes always live in the script's own store, also for foreign docsets."""
    if (not docset_name or "/" in docset_name or "\\" in docset_name
            or ".." in docset_name):
        raise CLIError("invalid docset name %r" % (docset_name,), 2)
    root = store if isinstance(store, str) else store.path
    return os.path.join(root, "notes", docset_name + ".md")


def parse_notes(text):
    """(general lines, {lowercased heading: [(type or None, lines)]})."""
    general: List[str] = []
    sections: dict = {}
    cur = None  # None = general; else the list the lines go to
    seen_content = False
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            heading = m.group(1)
            typ = None
            tm = _TYPED.match(heading)
            if tm:
                heading, typ = tm.group(1).strip(), tm.group(2).strip() or None
            if heading.lower() == "general" and typ is None:
                cur = general
            else:
                cur = []
                sections.setdefault(heading.lower(), []).append((typ, cur))
            seen_content = True
            continue
        if cur is None:
            if not line.strip():
                continue  # blank lines before any content
            if not seen_content and line.startswith("# "):
                seen_content = True  # leading title line
                continue
            cur = general
        if line.strip() or cur:
            seen_content = True
            cur.append(line)
    return general, sections


def _read_notes(store, docset_name):
    path = notes_path(store, docset_name)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return path, f.read()
    except OSError:
        return path, None


def _short_name(name) -> str:
    """Entry name without an argument list: 'f(a, [b])' -> 'f' (lowercased)."""
    short = re.sub(r"\s*\(.*$", "", name).strip().lower()
    return short or name.lower()


def notes_for(store, docset_name, entry_name, entry_type) -> List[str]:
    path, text = _read_notes(store, docset_name)
    if text is None:
        return []
    general, sections = parse_notes(text)
    body = []
    if any(l.strip() for l in general):
        body += ["## General"] + general
    want = entry_name.lower()
    wants = {want, _short_name(entry_name)}
    for key, items in sections.items():
        for typ, lines in items:
            named = key in wants and (typ is None or typ.lower() == (entry_type or "").lower())
            hit = named or (typ is not None and "%s (%s)" % (key, typ.lower()) == want)
            if hit and any(l.strip() for l in lines):
                body += ["## %s%s" % (entry_name, " (%s)" % typ if named and typ else "")] \
                    + lines
    if not body:
        return []
    return ["--- notes (%s) ---" % path] + body


def general_notes(store, docset_name) -> List[str]:
    path, text = _read_notes(store, docset_name)
    if text is None:
        return []
    general, _ = parse_notes(text)
    if not any(l.strip() for l in general):
        return []
    return ["--- notes (%s) ---" % path, "## General"] + general


def size_warnings(text) -> List[str]:
    general, sections = parse_notes(text)
    warns = []
    if len(general) > NOTES_GENERAL_MAX:
        warns.append("General notes are %d lines (limit %d); trim them"
                     % (len(general), NOTES_GENERAL_MAX))
    for name, items in sections.items():
        for typ, lines in items:
            if len(lines) > NOTES_SECTION_MAX:
                warns.append("section %r is %d lines (limit %d); trim it" % (
                    name + (" (%s)" % typ if typ else ""), len(lines),
                    NOTES_SECTION_MAX))
    total = len(text.splitlines())
    if total > NOTES_TOTAL_MAX:
        warns.append("notes file is %d lines (limit %s); trim it"
                     % (total, format(NOTES_TOTAL_MAX, ",")))
    return warns


def check_notes(text, entry_names) -> List[str]:
    warns = size_warnings(text)
    _, sections = parse_notes(text)
    shorts = {_short_name(n) for n in entry_names}
    for name, items in sections.items():
        for typ, _lines in items:
            full = "%s (%s)" % (name, typ.lower()) if typ else name
            if name not in entry_names and name not in shorts and full not in entry_names:
                import difflib
                close = difflib.get_close_matches(name, sorted(entry_names | shorts), 1, 0.6)
                warns.append("section %r matches no entry in the docset; a heading is an "
                             "entry name as search prints it, or its part before '('%s"
                             % (full, "; did you mean %r?" % close[0] if close else ""))
    return warns


def notes_matches(docset_name, text, entries) -> List[str]:
    """One line per notes section: which `show` prints it (up to 3 REFs)."""
    general, sections = parse_notes(text)
    written = {}  # lowercased heading -> heading as written
    for line in text.splitlines():
        if line.startswith("## "):
            written.setdefault(line[3:].strip().lower(), line[3:].strip())
    out = []
    if any(l.strip() for l in general):
        out.append("## General: shown by every show of this docset")
    for key, items in sections.items():
        for typ, _lines in items:
            refs = []
            for i, n, t, _p in entries:
                low = n.lower()
                named = key in (low, _short_name(n)) and (
                    typ is None or typ.lower() == (t or "").lower())
                if named or (typ is not None and "%s (%s)" % (key, typ.lower()) == low):
                    refs.append("%s:%d" % (docset_name, i))
            if refs:
                label = "%s%s" % (key, " (%s)" % typ if typ else "")
                label = written.get(label.lower(), label)
                more = " (+%d more)" % (len(refs) - 3) if len(refs) > 3 else ""
                out.append("## %s: shown by show %s%s" % (label, ", ".join(refs[:3]), more))
    return out


def cmd_notes(args):
    store = require_store(args)
    notes_path(store, args.docset)  # rejects names that are not plain names
    ds = pick_docset(find_docsets(store), args.docset)
    path = notes_path(store, ds.name)
    if args.path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(path)
        return 0
    _, text = _read_notes(store, ds.name)
    if text is None:
        print("notes file not present: %s" % path)
        return 0
    if args.check:
        entries = list(iter_entries(ds))
        names = {n.lower() for _i, n, _t, _p in entries}
        warns = check_notes(text, names)
        print("notes file present: %s" % path)
        for line in notes_matches(ds.name, text, entries):
            print(line)
        for w in warns:
            print("warning: " + w)
        if not warns:
            print("ok")
        return 1 if warns else 0
    else:
        sys.stdout.write(text)
    return 0


FTS_SNIPPET_TOKENS = 14


def fts_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61')")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        return False


def fts_path(store, name) -> str:
    return os.path.join(meta_dir(store), "fts", name + ".sqlite")


def docset_stamp(ds) -> str:
    """Staleness key: installed version, else the index file's mtime (int)."""
    if ds.version:
        return str(ds.version)
    try:
        return str(int(os.path.getmtime(index_path(ds.path))))
    except OSError:
        return ""


# Bump when what the index stores changes, so existing indexes are rebuilt
# (2: repeated footers left out).
FTS_FORMAT = 2


def fts_stamp(ds) -> str:
    return "%s|fts%d" % (docset_stamp(ds), FTS_FORMAT)


def _stored_stamp(db):
    if not os.path.isfile(db):
        return None
    try:
        con = _open_ro(db)
        try:
            row = con.execute(
                "SELECT value FROM meta WHERE key='docset_version'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def build_fts(store, ds) -> int:
    """(Re)build the docset's full-text index; return the pages indexed."""
    pages = {}  # page file -> [entry ids]
    for entry_id, _n, _t, path in iter_entries(ds):
        if re.match(r"https?://", path, re.I):
            continue
        file_part, _anchor = entry_location(path)
        if file_part:
            pages.setdefault(file_part, []).append(entry_id)
    db = fts_path(store, ds.name)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    tmp = db + ".tmp"
    if os.path.exists(tmp):
        os.unlink(tmp)
    con = sqlite3.connect(tmp)
    count = 0
    try:
        con.executescript(
            "CREATE VIRTUAL TABLE pages USING fts5(path UNINDEXED, text, "
            "tokenize='unicode61');"
            "CREATE TABLE page_entries(path TEXT, entry_id INTEGER);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
        for file_part, ids in pages.items():
            try:
                blocks = page_blocks(store, ds, file_part)
            except (CLIError, OSError):
                continue
            text = "\n".join(b.text for b in blocks)
            con.execute("INSERT INTO pages(path, text) VALUES (?, ?)", (file_part, text))
            con.executemany("INSERT INTO page_entries VALUES (?, ?)",
                            [(file_part, i) for i in ids])
            count += 1
        con.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("docset_version", fts_stamp(ds)),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))])
        con.commit()
    except BaseException:
        con.close()
        os.unlink(tmp)
        raise
    con.close()
    os.replace(tmp, db)
    return count


def ensure_fts(store, ds) -> None:
    """Build a missing index; rebuild a stale one (noting it on stderr)."""
    stored = _stored_stamp(fts_path(store, ds.name))
    if stored == fts_stamp(ds):
        return
    if stored is None:
        print("note: building the full-text index for %s (first use; large "
              "docsets take a while; index-text builds it ahead)" % ds.name,
              file=sys.stderr)
    build_fts(store, ds)
    if stored is not None:
        _warn("rebuilt index for %s" % ds.name)


def fts_match_expr(query) -> str:
    """Quote each token as an FTS5 phrase and AND them (user text is data)."""
    return " AND ".join('"%s"' % t.replace('"', '""') for t in query.split())


def _snippet_phrases(snippet) -> List[str]:
    """Phrases around the first match of an FTS snippet (matches marked
    \x02...\x03), longest first: two words before it plus up to three from
    it, then just the latter."""
    m = re.search("\x02", snippet)
    if not m:
        return []
    before = snippet[:m.start()].split("...")[-1].split()[-2:]
    after = re.split(r"\.\.\.|[.!?;:](?:\s|$)|\s-\s",
                     re.sub("[\x02\x03]", "", snippet[m.start():]))[0].split()[:3]
    clean = lambda ws: " ".join(ws).strip(" .,;:!?()").lower()
    return [p for p in dict.fromkeys([clean(before + after), clean(after)]) if p]


def match_anchor(ds, path, query, snippet="") -> Optional[List[str]]:
    """Ids of the nearest block with ids at or before the match (located via
    the FTS snippet, else the first block holding the query words), if any."""
    try:
        blocks = read_page_blocks(ds, path)
    except (CLIError, OSError):
        return None
    words = [w.lower() for w in query.split()]
    if not words:
        return None
    texts = [b.text.lower() for b in blocks]
    last_id, anchor_at = None, []
    for b in blocks:  # nearest id at or before each block
        if b.ids:
            last_id = list(b.ids)  # every id of the block: any may be an entry's
        anchor_at.append(last_id)
    texts = [" ".join(t.split()) for t in texts]
    tests = [(lambda t, p=p: p in t) for p in _snippet_phrases(snippet)]
    tests += [lambda t: all(w in t for w in words), lambda t: words[0] in t]
    for test in tests:
        for i, t in enumerate(texts):
            if anchor_at[i] and test(t):
                return anchor_at[i]
    return None


def _unquote_all(text) -> str:
    """URL-decode until stable (Dash anchors are sometimes encoded twice)."""
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    return text


def _anchor_entries(ds) -> dict:
    """{(page file, decoded anchor): lowest entry id} for the docset's entries."""
    found: dict = {}
    for entry_id, _n, _t, path in iter_entries(ds):
        file_part, anchor = entry_location(path)
        if anchor:
            key = (file_part, _unquote_all(anchor))
            if key not in found or entry_id < found[key]:
                found[key] = entry_id
    return found


def fts_search(store, docsets, query, limit) -> List[dict]:
    expr = fts_match_expr(query)
    if not expr:
        return []
    scored = []
    for ds in docsets:
        entry_at = None  # built on the first hit with an anchor
        db = fts_path(store, ds.name)
        try:
            con = _open_ro(db)
            try:
                rows = con.execute(
                    "SELECT path, snippet(pages, 1, char(2), char(3), '...', %d), "
                    "bm25(pages) FROM pages WHERE pages MATCH ? "
                    "ORDER BY bm25(pages) LIMIT ?" % FTS_SNIPPET_TOKENS,
                    (expr, limit)).fetchall()
                for path, snip, score in rows:
                    ref = "%s:page:%s" % (ds.name, path)
                    ids = match_anchor(ds, path, query, snip)  # \x02 marks matches
                    if ids:
                        if entry_at is None:
                            entry_at = _anchor_entries(ds)
                        entry_id = next((entry_at[(path, _unquote_all(a))] for a in ids
                                         if (path, _unquote_all(a)) in entry_at), None)
                        # an anchor that is an entry's: the short entry REF
                        ref = ("%s:%d" % (ds.name, entry_id) if entry_id is not None
                               else ref + "#" + quote(ids[0], safe=":/()$"))
                    scored.append((score, ds.name, path, {
                        "ref": ref, "docset": ds.name, "path": path,
                        "snippet": " ".join(snip.split()).replace(
                            "\x02", "[").replace("\x03", "]")}))
            finally:
                con.close()
        except sqlite3.Error as e:
            _warn("skipping %s: %s" % (ds.name, e))
    scored.sort(key=lambda h: h[:3])
    return [h[3] for h in scored[:limit]]


def _need_fts():
    if not fts_available():
        raise CLIError("this Python's sqlite3 has no FTS5 support; full-text "
                       "search is unavailable (docset search still works)", 2)


def cmd_index_text(args):
    _need_fts()
    store = require_store(args)
    all_docs = find_docsets(store)
    if not args.args:
        raise CLIError("name the docsets to index", 2)
    picked = {}
    for n in args.args:
        d = pick_docset(all_docs, n)
        picked[d.name] = d
    for d in picked.values():
        count = build_fts(store, d)
        print("indexed %d pages of %s" % (count, d.name))
    return 0


FTS_MAX_LINES = 11  # 5 hits (two lines each) plus the "more hits cut" line


def cmd_fts(args):
    _join_query(args)
    if not args.query.strip():
        raise CLIError("empty search query", 2)
    _need_fts()
    store = require_store(args)
    docs = select_docsets(store, find_docsets(store), args.docset or [], args.all)
    for ds in docs:
        ensure_fts(store, ds)
    # text output takes two lines per hit: fetch enough hits to reach the line cap
    limit = args.max_lines if args.json else args.max_lines // 2 + 1
    hits = fts_search(store, docs, args.query, limit)
    if args.json:
        print(json.dumps(hits, indent=2))
        return 0
    if not hits:
        print("no matches for %r" % args.query)
        return 0
    room = max(1, (args.max_lines - 1) // 2) if len(hits) * 2 > args.max_lines else len(hits)
    for h in hits[:room]:
        print(h["ref"])
        print("    " + h["snippet"])
    if len(hits) > room:
        print("... more hits cut; add words (e.g. the function name), -d, or "
              "raise --max-lines")
    return 0


# --- sources (contributed docsets), remove, the network ---------------------

# This script never contacts kapeli.com or its mirrors: Kapeli asked that
# tools add no load to his servers (the user, 2026-11-16). Every docset
# archive (official, cheat sheet, user-contributed) is served only from
# there, so the script downloads no docsets: Dash and Zeal do, and the
# script reads their folders (--read-from). `sources` only searches the list
# of user-contributed docsets. Every request goes through _request, which
# refuses these hosts and redirects to them.
BLOCKED_HOSTS = ("kapeli.com",)
# User-contributed docsets: one folder per docset under docsets/ in the
# Kapeli/Dash-User-Contributions repo on GitHub (it keeps each docset.json,
# not the archives). One request lists them all (630 in 2026-11; the API
# lists at most 1000 entries of a folder).
CONTRIB_LIST_URL = ("https://api.github.com/repos/Kapeli/Dash-User-Contributions"
                    "/contents/docsets")
# Zeal's combined catalog: a best-effort public service with no stability
# promise. Used only when the GitHub list fails, checked at most weekly
# (conditional request), never retried within a day of a failure, and
# cached without its icons. Entries: {name, title, sourceId, versions, ...};
# contributed docsets have sourceId com.kapeli.contrib.
ZEAL_CATALOG_URL = "https://api.zealdocs.org/_api/v1/catalog.json"
ZEAL_MAX_AGE = 7 * 86400
RETRY_AFTER_FAILURE = 86400
CACHE_MAX_AGE = 7 * 86400
# Unambiguous on purpose: a server can filter or rate-limit this script by it
# (the user, 2026-11-15).
USER_AGENT = f"docset-agent-skill-RJS/{VERSION}"
NET_TIMEOUT = 60

GET_DOCSETS = ("This script downloads no docsets. Download one in Dash (Settings > "
               "Downloads > User Contributed) or Zeal (Tools > Docsets > Available), "
               "then read Dash's or Zeal's docset folder with: docset.py where --set "
               "STORE --read-from DIR (where --discover finds DIR).")


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def blocked_host(url) -> bool:
    """True for a URL on a host this script never contacts (BLOCKED_HOSTS)."""
    try:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def _refuse_blocked(url):
    if blocked_host(url):
        raise FetchError("refused %s: this script never contacts kapeli.com; "
                         "Dash and Zeal download docsets" % url)


class NoBlockedRedirect(urllib.request.HTTPRedirectHandler):
    """Follows redirects except to a blocked host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _refuse_blocked(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(NoBlockedRedirect)


def _request(url, method="GET", headers=None):
    _refuse_blocked(url)
    req = urllib.request.Request(url, method=method,
                                 headers=dict(headers or {}, **{"User-Agent": USER_AGENT}))
    try:
        return _opener().open(req, timeout=NET_TIMEOUT)
    except urllib.error.HTTPError as e:
        raise FetchError("HTTP %d for %s" % (e.code, url), e.code)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise FetchError("cannot reach %s: %s" % (url, getattr(e, "reason", e)))


def fetch(url: str) -> bytes:
    """GET url (redirects followed, never to a blocked host)."""
    with _request(url) as r:
        try:
            return r.read()
        except (OSError, http.client.HTTPException) as e:
            raise FetchError("download of %s failed: %s" % (url, e))


def fetch_cond(url: str, etag=None, last_modified=None):
    """Conditional GET: (body, etag, last_modified); body None on 304."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        r = _request(url, headers=headers)
    except FetchError as e:
        if e.status == 304:
            return None, etag, last_modified
        raise
    with r:
        try:
            body = r.read()
        except (OSError, http.client.HTTPException) as e:
            raise FetchError("download of %s failed: %s" % (url, e))
        return body, r.headers.get("ETag"), r.headers.get("Last-Modified")


def cached_get(store, key, url, max_age, force=False, transform=None) -> bytes:
    """Body of url, kept in the cache with its ETag/Last-Modified.

    Re-checked at most every max_age seconds (force skips that wait), with a
    conditional request so an unchanged file is not downloaded again; after
    a failure, not retried for RETRY_AFTER_FAILURE (the cached copy, if any,
    is used meanwhile). transform(bytes) shrinks a new body before saving."""
    d = os.path.join(meta_dir(store), "cache")
    body_p = os.path.join(d, key + ".body")
    meta_p = os.path.join(d, key + ".meta.json")
    try:
        meta = _load_json(meta_p) if os.path.isfile(meta_p) else {}
    except CLIError:
        meta = {}
    have = os.path.isfile(body_p)
    now = time.time()

    def cached():
        with open(body_p, "rb") as f:
            return f.read()

    if have and not force and 0 <= now - meta.get("checked", -max_age - 1) < max_age:
        return cached()
    failed = meta.get("failed")
    if isinstance(failed, (int, float)) and 0 <= now - failed < RETRY_AFTER_FAILURE:
        if have:
            return cached()
        raise FetchError("%s failed less than a day ago (%s); not retrying yet"
                         % (url, meta.get("error", "")))
    os.makedirs(d, exist_ok=True)
    try:
        body, etag, lm = fetch_cond(url, meta.get("etag") if have else None,
                                    meta.get("last_modified") if have else None)
        if body is not None and transform:
            body = transform(body)
    except (FetchError, ValueError) as e:
        meta.update(failed=now, error=str(e))
        _write_json(meta_p, meta)
        if have:
            _warn("using the cached copy of %s; refresh failed: %s" % (url, e))
            return cached()
        raise
    if body is not None:
        tmp = body_p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, body_p)
        meta = {"etag": etag, "last_modified": lm}
    meta.pop("failed", None)
    meta.pop("error", None)
    meta["checked"] = now
    _write_json(meta_p, meta)
    return body if body is not None else cached()


def _slim_catalog(body: bytes) -> bytes:
    """Zeal catalog without icons and other fields we never read."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Zeal catalog is not a list")
    keep = ("name", "title", "sourceId", "versions")
    return json.dumps([{k: e.get(k) for k in keep if k in e}
                       for e in data if isinstance(e, dict) and e.get("name")]).encode()


def _slim_contrib(body: bytes) -> bytes:
    """GitHub folder listing -> the sorted names of its subfolders."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("the GitHub listing is not a list")
    return json.dumps(sorted(str(i["name"]) for i in data if isinstance(i, dict)
                             and i.get("type") == "dir" and i.get("name"))).encode()


def zeal_catalog(store) -> List[dict]:
    """Last resort only (see ZEAL_CATALOG_URL); never forced to refresh."""
    return json.loads(cached_get(store, "zeal-catalog", ZEAL_CATALOG_URL,
                                 ZEAL_MAX_AGE, transform=_slim_catalog).decode("utf-8"))


def _first_version(e) -> str:
    return next((str(v) for v in e.get("versions") or [] if v), "")


_SOURCE_ERRORS = (FetchError, ValueError, KeyError, TypeError, AttributeError)


def contributed(store, refresh: bool) -> List[Tuple[str, str, str]]:
    """(name, version, title) of each user-contributed docset: from GitHub
    (names only), from Zeal's catalog only when GitHub fails."""
    try:
        names = json.loads(cached_get(store, "contrib-list", CONTRIB_LIST_URL,
                                      CACHE_MAX_AGE, force=refresh,
                                      transform=_slim_contrib).decode("utf-8"))
        return [(str(n), "", "") for n in names]
    except _SOURCE_ERRORS as first:
        try:
            out = [(str(e["name"]), _first_version(e), str(e.get("title") or ""))
                   for e in zeal_catalog(store)
                   if isinstance(e, dict) and e.get("sourceId") == "com.kapeli.contrib"]
        except _SOURCE_ERRORS as e:
            raise CLIError("cannot load the contributed docset list (GitHub: %s; "
                           "Zeal's catalog: %s)" % (first, e), 7)
        print("note (no action needed): the list came from Zeal's catalog; GitHub "
              "was unreachable (%s)" % first, file=sys.stderr)
        return out


def _norm(name):
    return re.sub(r"[\s_]+", "_", name.strip().lower())


def cmd_sources(args):
    _join_query(args)
    store = require_store(args)
    q = _norm(args.query) if args.query else ""
    here = {_norm(d.name): d.name for d in find_docsets(store)}
    lines = []
    for name, version, title in sorted(contributed(store, args.refresh),
                                       key=lambda x: x[0].lower()):
        if q not in _norm(name) and not (title and q in _norm(title)):
            continue
        line = name + ("  " + version if version else "")
        if title and title != name:
            line += "  (%s)" % title
        have = here.get(_norm(name)) or (here.get(_norm(title)) if title else None)
        if have:
            line += "  (already here as %s)" % have
        lines.append(line)
    if not lines:
        print("no contributed docset matches %r" % (args.query or ""))
        print(GET_DOCSETS)
        return 5
    for line in cap_lines(lines, args.max_lines, "raise --max-lines or give a QUERY"):
        print(line)
    print(GET_DOCSETS)
    return 0


REMOVED_COMMANDS = ("install", "update")
REMOVED_MESSAGE = ("`%s` was removed: this script no longer downloads docsets (every "
                   "docset archive is on kapeli.com, which it never contacts). "
                   "Download or update docsets in Dash or Zeal; `docset.py sources "
                   "QUERY` searches the user-contributed ones. Docsets already in "
                   "Dash's or Zeal's folder are read in place (references/setup.md).")


def _managed(store, name):
    """The installed.json entry for name, or a CLIError (5 unknown, 2 not ours)."""
    installed = load_installed(store)
    if name in installed and isinstance(installed[name], dict):
        return installed[name]
    if any(d.name == name for d in find_docsets(store)):
        raise CLIError("%s was not installed by docset.py (foreign or hand-copied); "
                       "manage it with the tool that owns it" % name, 2)
    raise CLIError("unknown docset %r (see: docset.py list)" % name, 5)


def cmd_remove(args):
    store = require_store(args)
    _managed(store, args.name)
    path = os.path.join(store.path, args.name + ".docset")
    try:
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    except OSError as e:
        raise CLIError("cannot remove %s: %s" % (path, e), 7)
    try:
        os.unlink(fts_path(store, args.name))
    except OSError:
        pass
    installed = load_installed(store)
    installed.pop(args.name, None)
    save_installed(store, installed)
    print("removed %s" % args.name)
    if os.path.exists(notes_path(store, args.name)):
        print("notes kept: " + notes_path(store, args.name))
    return 0


EXIT_CODES = ("0 ok; 1 notes --check found problems; 2 usage, unknown name or "
              "no FTS5; 3 storage location not set; 4 search scope too wide "
              "(use -d, a project list or --all); 5 not found; 7 network (the "
              "contributed docset list could not be loaded)")

# Top-level --help: the command lines agents normally need. Options used
# here are listed in COMMON_OPTIONS; every other option of a subcommand is
# named (not described) under "only if you need these", generated from the
# parser, so a new option can't be left out (a test checks both lists).
TOP_HELP = """\
dash-docset {version}: search Dash docsets offline (stdlib only).
This is the command reference; `<command> --help` adds only the options
listed at the end. REF = <Docset>:<id> or <Docset>:page:<path>[#anchor],
as search and fts print them; <Docset> is the name `list` prints.

Look up (usual order):
  search QUERY... [-d NAME]      entries whose names contain all the words;
                                 prints one REF per entry, best first
  show REF                       that entry's section (max 150 lines) plus
                                 your notes for it
  show REF --grep TEXT           only lines containing TEXT, with their
                                 heading, table header row, and a matching
                                 term's definition (repeatable; plain text,
                                 not a pattern)
  fts QUERY... [-d NAME]         words inside pages, 5 best hits with REFs;
                                 include the function name: fts read_csv skip

Notes (format: references/notes.md in the skill folder):
  notes DOCSET --path            the notes file to edit
  notes DOCSET --check           after editing: which REFs show each section,
                                 then "ok"

Set up and manage (references/setup.md, references/getting-docsets.md):
  where                          the store in use; exit 3 = not set yet
  where --set PATH --project|--user [--read-from DIR]
                                 save the store the user chose; DIR = Dash's
                                 or Zeal's docset folder (where --discover)
  list                           docsets found and their versions
  sources QUERY...               user-contributed docsets to download in Dash
                                 or Zeal (this script downloads none)
  remove NAME | index-text DOCSET (build fts index now)

Only if you need these, see `<command> --help`:
{rare}
Global: --dir PATH (use this store for one run), --version.
{exit_codes}
"""
COMMON_OPTIONS = {"search": {"-d"}, "fts": {"-d"}, "show": {"--grep"},
                  "notes": {"--path", "--check"},
                  "where": {"--set", "--project", "--user", "--read-from"}}


def subcommand_options(parser) -> dict:
    """{subcommand: its option strings (short form if any), minus -h}."""
    out = {}
    for name, p in parser._dash_sub.choices.items():
        opts = []
        for a in p._actions:
            if a.option_strings and "-h" not in a.option_strings:
                opts.append(a.option_strings[0])
        out[name] = opts
    return out


def top_help(parser) -> str:
    rare = []
    for name, opts in subcommand_options(parser).items():
        extra = [o for o in opts if o not in COMMON_OPTIONS.get(name, set())]
        if extra:
            rare.append("  %-10s %s" % (name, " ".join(extra)))
    import textwrap
    codes = textwrap.fill("Exit codes: " + EXIT_CODES, width=76,
                          subsequent_indent="  ")
    return TOP_HELP.format(version=VERSION, rare="\n".join(rare), exit_codes=codes)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="docset.py", description=f"dash-docset {VERSION}: {__doc__}",
        add_help=False)
    parser.add_argument("-h", "--help", action="store_true",
                        help="show the command reference")
    parser.add_argument("--version", action="version",
                        version=f"dash-docset {VERSION}")
    parser.add_argument("--dir", metavar="PATH",
                        help="use this docset store (overrides DASH_DOCSET_DIR and config)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    parser._dash_sub = sub
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
            p.add_argument("--replace", action="store_true",
                           help="with --set: switch stores although a config "
                                "already names another one")
            p.set_defaults(handler=cmd_where)
            continue
        if name == "list":
            p.set_defaults(handler=cmd_list)
            continue
        if name == "sources":
            p.add_argument("query", nargs="*", metavar="QUERY",
                           help="only docsets whose name, title or keywords contain this text")
            p.add_argument("--refresh", action="store_true",
                           help="refetch the source lists (cached for 7 days)")
            p.add_argument("--max-lines", type=positive_int, default=40, metavar="N",
                           help="print at most N lines (default 40)")
            p.set_defaults(handler=cmd_sources)
            continue
        if name == "remove":
            p.add_argument("name", metavar="NAME")
            p.set_defaults(handler=cmd_remove)
            continue
        if name == "show":
            p.add_argument("ref", metavar="REF", help="<Docset>:<id> from search, or <Docset>:page:<path>[#anchor] from fts")
            p.add_argument("--full", action="store_true",
                           help="print the whole trimmed section, without the line cap")
            p.add_argument("--max-lines", type=positive_int, default=150, metavar="N",
                           help="print at most N lines (default 150)")
            p.add_argument("--no-notes", action="store_true",
                           help="do not append notes")
            p.add_argument("--grep", metavar="TEXT", action="append",
                           help="print only lines containing TEXT (case-insensitive; "
                           "repeatable), with their heading and table header row")
            p.set_defaults(handler=cmd_show)
            continue
        if name == "search":
            p.add_argument("query", nargs="+", metavar="QUERY")
            p.add_argument("-d", "--docset", metavar="NAME", action="append",
                           help="search only this docset (repeatable)")
            p.add_argument("--all", action="store_true",
                           help="search every docset (needed when more than 4 "
                           "are full-size and no project list is set)")
            p.add_argument("--type", metavar="TYPE",
                           help="only entries of this type (case-insensitive)")
            p.add_argument("--max-lines", type=positive_int, default=40, metavar="N",
                           help="print at most N results (default 40)")
            p.add_argument("--json", action="store_true",
                           help="print a JSON list of {ref, docset, type, name, rank}")
            p.set_defaults(handler=cmd_search)
            continue
        if name == "fts":
            p.add_argument("query", nargs="+", metavar="QUERY")
            p.add_argument("-d", "--docset", metavar="NAME", action="append",
                           help="search only this docset (repeatable)")
            p.add_argument("--all", action="store_true",
                           help="search every docset (needed when more than 4 "
                           "are full-size and no project list is set)")
            p.add_argument("--max-lines", type=positive_int, default=FTS_MAX_LINES,
                           metavar="N", help="print at most N lines (default %d: "
                           "%d hits)" % (FTS_MAX_LINES, (FTS_MAX_LINES - 1) // 2))
            p.add_argument("--json", action="store_true",
                           help="print a JSON list of {ref, docset, path, snippet}")
            p.set_defaults(handler=cmd_fts)
            continue
        if name == "index-text":
            p.add_argument("args", nargs="*", metavar="DOCSET",
                           help="docsets to (re)build the full-text index for")
            p.set_defaults(handler=cmd_index_text)
            continue
        if name == "notes":
            p.add_argument("docset", metavar="DOCSET")
            g = p.add_mutually_exclusive_group()
            g.add_argument("--check", action="store_true",
                           help="warn about oversized notes and headings matching "
                           "no entry; exit 1 if any")
            g.add_argument("--path", action="store_true",
                           help="print the notes file path, creating notes/ (edit the file "
                                "with normal tools)")
            p.set_defaults(handler=cmd_notes)
            continue
    return parser


def _command_word(argv) -> Optional[str]:
    """The subcommand in argv: the first word that is not an option or --dir's value."""
    skip = False
    for a in argv:
        if skip:
            skip = False
        elif a == "--dir":
            skip = True
        elif not a.startswith("-"):
            return a
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    word = _command_word(argv)
    if word in REMOVED_COMMANDS:
        print(REMOVED_MESSAGE % word, file=sys.stderr)
        return 2
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        print(top_help(parser), end="")
        return 0 if args.help else 2
    try:
        return args.handler(args)
    except CLIError as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
