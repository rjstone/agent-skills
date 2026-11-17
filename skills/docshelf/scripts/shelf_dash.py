"""docshelf Dash backend: read-only access to Dash/Zeal docsets."""
import hashlib
import io
import json
import os
import pathlib
import plistlib
import posixpath
import re
import shutil
import sqlite3
import sys
import tarfile
import zlib
from typing import List, Optional, Tuple
from urllib.parse import unquote

from shelf_core import CLIError, Docvol, Entry, resolve_doc_path, warn

INDEX_REL = ("Contents", "Resources", "docSet.dsidx")
DOCS_REL = ("Contents", "Resources", "Documents")
# Tarix docsets (Dash's compact storage; read by Zeal's tarixarchive.cpp):
# Contents/Resources/tarix.tgz is a normal .tgz written with a zlib full flush
# before every tar record, and tarixIndex.db is SQLite with
# tarindex(path TEXT PRIMARY KEY COLLATE NOCASE, hash TEXT), where path starts
# "<Name>.docset/" and hash is "<block> <offset> <length>": the compressed
# byte offset of a flush point and the record size in 512-byte blocks. Pages
# are read one at a time without unpacking. (Kapeli serves the index as
# <archive>.tgz.tarix: a .tgz holding that SQLite file.)
TARIX_MAX_RECORD = 64 * 1024 * 1024
_FAMILY_VERSION = re.compile(r"[_-]\d+(\.\d+)*$")


def dash_family(name: str) -> str:
    """'Python_3' -> 'python', 'Node.js' -> 'node.js', 'Qt_6.5' -> 'qt'."""
    return _FAMILY_VERSION.sub("", name.lower().replace(" ", "_"))


def entry_location(path: str) -> Tuple[str, Optional[str]]:
    """Index path -> (page file, anchor or None): marker tags dropped, file
    decoded, backslashes turned into '/'."""
    path = re.sub(r"<dash_entry_[^>]*>", "", path)
    file_part, sep, anchor = path.partition("#")
    return unquote(file_part).replace("\\", "/"), (anchor if sep and anchor else None)


def _open_ro(path: str) -> sqlite3.Connection:
    # mode=ro, never immutable=1: a WAL index keeps its rows in the -wal file,
    # which immutable=1 ignores.
    uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _table(con) -> str:
    tables = _tables(con)
    for t in ("searchIndex", "ZTOKEN"):
        if t in tables:
            return t
    raise ValueError("no searchIndex or ZTOKEN table")


_SQL_SEARCH = "SELECT id, name, type, path FROM searchIndex ORDER BY id"
_SQL_ZTOKEN = ("SELECT k.Z_PK, k.ZTOKENNAME, ty.ZTYPENAME, f.ZPATH, m.ZANCHOR "
               "FROM ZTOKEN k "
               "LEFT JOIN ZTOKENTYPE ty ON ty.Z_PK = k.ZTOKENTYPE "
               "LEFT JOIN ZTOKENMETAINFORMATION m ON m.Z_PK = k.ZMETAINFORMATION "
               "LEFT JOIN ZFILEPATH f ON f.Z_PK = m.ZFILE ORDER BY k.Z_PK")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class DashDocvol(Docvol):
    def __init__(self, path: str, source: str, cache_dir: str):
        self.path = os.path.abspath(path)
        self.cache_dir = cache_dir
        self.source = source
        self.read_only = True
        self.shadowed: List[str] = []  # later copies of this name, not used
        self.name = os.path.basename(self.path)[:-len(".docset")] \
            if self.path.endswith(".docset") else os.path.basename(self.path)
        self.family = dash_family(self.name)
        self.title = self.name
        try:
            with open(os.path.join(self.path, "Contents", "Info.plist"), "rb") as f:
                plist = plistlib.load(f)
            if isinstance(plist, dict) and plist.get("CFBundleName"):
                self.title = str(plist["CFBundleName"])
        except Exception:  # any unreadable plist (e.g. ExpatError): keep the name
            pass
        self.display_name = self.title
        meta = _load_json(os.path.join(self.path, "meta.json"))
        self.version = str(meta.get("version") or "")
        self.release = self.version
        self.docs_dir = os.path.join(self.path, *DOCS_REL)
        self.index_file = os.path.join(self.path, *INDEX_REL)
        self._entries: Optional[List[Entry]] = None
        self._pages: Optional[List[str]] = None
        self._known: Optional[set] = None
        self._use_copy = False
        with self._connect() as con:
            self.entry_count = con.execute(
                "SELECT COUNT(*) FROM %s" % _table(con)).fetchone()[0]

    def data_dir(self) -> str:
        digest = hashlib.sha1(self.path.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self.cache_dir, "docsets", "%s-%s" % (self.name, digest))

    def _copy_index(self) -> str:
        dest_dir = os.path.join(self.data_dir(), "index")
        os.makedirs(dest_dir, exist_ok=True)
        for suffix in ("", "-wal"):
            src = self.index_file + suffix
            dest = os.path.join(dest_dir, "docSet.dsidx" + suffix)
            if os.path.exists(src):
                shutil.copyfile(src, dest)
            elif os.path.exists(dest):
                os.remove(dest)
        return os.path.join(dest_dir, "docSet.dsidx")

    def _connect(self) -> "_Conn":
        """Open the index read-only; if that fails (a WAL index in a
        read-only folder has no -shm file), read a copy kept in data_dir()."""
        if not self._use_copy:
            con = None
            try:
                con = _open_ro(self.index_file)
                con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
                return _Conn(con)
            except sqlite3.OperationalError:
                if con is not None:
                    con.close()
                self._use_copy = True
        return _Conn(_open_ro(self._copy_index()))

    def entries(self) -> List[Entry]:
        if self._entries is None:
            out = []
            with self._connect() as con:
                form = _table(con)
                sql = _SQL_SEARCH if form == "searchIndex" else _SQL_ZTOKEN
                for row in con.execute(sql):
                    i, name, typ, path = row[:4]
                    path = path or ""
                    if form == "ZTOKEN" and row[4]:
                        path += "#" + row[4]
                    if not path or re.match(r"https?://", path, re.I):
                        continue
                    page, anchor = entry_location(path)
                    out.append(Entry(name or "", typ or "",
                                     "%s:%d" % (self.name, i), page, anchor))
            self._entries = out
        return self._entries

    def pages(self) -> List[str]:
        if self._pages is None:
            self._pages = list(dict.fromkeys(e.page for e in self.entries()))
        return self._pages

    def _doc_file(self, page: str) -> str:
        docs = self.docs_dir
        full = os.path.normpath(os.path.join(docs, *page.split("/")))
        try:
            inside = os.path.commonpath([docs, full]) == docs
        except ValueError:
            inside = False
        if not inside or not os.path.isfile(full):
            raise CLIError("no page %r in %s" % (page, self.name), 5)
        return full

    def _tarix_rel(self, page: str) -> str:
        """Archive-relative path of page; CLIError 5 if it escapes Documents/."""
        rel = posixpath.normpath(page.replace("\\", "/")).lstrip("/")
        if rel == ".." or rel.startswith("../") or rel == ".":
            raise CLIError("no page %r in %s" % (page, self.name), 5)
        return "Contents/Resources/Documents/" + rel

    def _tarix_row(self, rel: str) -> Optional[str]:
        """The index hash for rel, or None when there is no archive or no
        such entry. The index is opened per lookup and closed again."""
        res = os.path.join(self.path, "Contents", "Resources")
        idx = os.path.join(res, "tarixIndex.db")
        if not (os.path.isfile(os.path.join(res, "tarix.tgz")) and os.path.isfile(idx)):
            return None
        try:
            with _Conn(_open_ro(idx)) as con:
                row = con.execute("SELECT path FROM tarindex WHERE path LIKE "
                                  "'%.docset/%' LIMIT 1").fetchone()
                if not row:
                    return None
                prefix = row[0][:row[0].index(".docset/") + len(".docset/")]
                row = con.execute("SELECT hash FROM tarindex WHERE path = ?",
                                  (prefix + rel,)).fetchone()
        except (sqlite3.Error, ValueError) as e:
            raise CLIError("tarix index error for %s: %s" % (rel, e), 7)
        return str(row[0]) if row and row[0] else None

    def _read_tarix(self, rel: str, hash_: str) -> bytes:
        try:
            _block, offset, blocks = (int(x) for x in hash_.split())
        except ValueError:
            raise CLIError("bad tarix index entry for %s" % rel, 7)
        want = blocks * 512
        if offset < 0 or blocks < 1 or want > TARIX_MAX_RECORD:
            raise CLIError("bad tarix index entry for %s" % rel, 7)
        out = bytearray()
        try:
            with open(os.path.join(self.path, "Contents", "Resources", "tarix.tgz"), "rb") as f:
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

    def page_html(self, page: str) -> str:
        try:
            path = self._doc_file(page)
        except CLIError:
            rel = self._tarix_rel(page)  # refuses a path that escapes Documents/
            hash_ = self._tarix_row(rel)
            if hash_ is None:
                raise
            return self._read_tarix(rel, hash_).decode("utf-8", errors="replace")
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    def resolve_href(self, page: str, href: str) -> Optional[str]:
        target, frag = resolve_doc_path(page, href)
        try:
            self._doc_file(target)
        except CLIError:
            try:
                if self._tarix_row(self._tarix_rel(target)) is None:
                    return None
            except CLIError:
                return None
        return self.make_ref(target, frag)

    def resolve(self, rest: str) -> Tuple[str, Optional[str], Optional[Entry]]:
        if rest.isascii() and rest.isdecimal():
            ref = "%s:%s" % (self.name, int(rest))
            for e in self.entries():
                if e.ref == ref:
                    return e.page, e.anchor, e
            raise CLIError("no entry %s in %s" % (rest, self.name), 5)
        if rest.startswith("page:") and len(rest) > 5:
            path, _, anchor = rest[5:].partition("#")
            return path, anchor or None, None
        raise CLIError("bad reference %r: expected %s:<id> or %s:page:<path>[#anchor]"
                       % (rest, self.name, self.name), 2)

    def make_ref(self, page: str, anchor: Optional[str]) -> str:
        return "%s:page:%s%s" % (self.name, page, "#" + anchor if anchor else "")

    def stamp(self) -> str:
        parts = []
        for f in (self.index_file, self.index_file + "-wal",
                  os.path.join(self.path, "Contents", "Resources", "tarix.tgz")):
            try:
                st = os.stat(f)
                parts.append("%d:%d" % (st.st_size, int(st.st_mtime)))
            except OSError:
                parts.append("-")
        return "|".join(parts)


class _Conn:
    """A sqlite connection that closes on exit."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, *exc):
        self.con.close()


def open_docset(path: str, source: str, cache_dir: str) -> Optional[DashDocvol]:
    try:
        return DashDocvol(path, source, cache_dir)
    except (sqlite3.Error, OSError, ValueError) as e:
        warn("skipping unreadable docset %s: %s" % (path, e))
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
# Dash (macOS): ~/Library/Application Support/Dash/DocSets/<Name>/<Name>.docset.
# Dash for Windows (Store package): %LOCALAPPDATA%\Packages\<Kapeli.Dash_...>,
# docsets somewhere below it.
# Every location comes from the env mapping given, never from the process.


def _home(env) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or ""


def _join(base: str, *parts: str) -> Optional[str]:
    return os.path.join(base, *parts) if base else None


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
    out: List[Optional[str]] = []
    conf_home = env.get("XDG_CONFIG_HOME") or _join(home, ".config")
    if conf_home:
        out.append(_ini_docsets_path(os.path.join(conf_home, "Zeal", "Zeal.conf")))
    if home:
        out.append(_ini_docsets_path(os.path.join(
            home, ".var", "app", "org.zealdocs.Zeal", "config", "Zeal", "Zeal.conf")))
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


def _dash_windows_packages(env) -> List[str]:
    """Dash for Windows package folders: names containing "dash" and "kapeli"."""
    pkgs = _join(env.get("LOCALAPPDATA", ""), "Packages")
    try:
        names = sorted(os.listdir(pkgs)) if pkgs else []
    except OSError:
        return []
    return [os.path.join(pkgs, n) for n in names
            if "dash" in n.lower() and "kapeli" in n.lower()
            and os.path.isdir(os.path.join(pkgs, n))]


def viewer_apps(env) -> List[Tuple[str, str]]:
    """Installed Dash or Zeal apps: (app, where found)."""
    home = _home(env)
    checks = [("Dash", p) for p in (
        "/Applications/Dash.app", "/Applications/Setapp/Dash.app",
        _join(home, "Applications", "Dash.app"))]
    checks += [("Dash", p) for p in _dash_windows_packages(env)]
    checks += [("Zeal", p) for p in (
        "/Applications/Zeal.app",
        _join(home, ".var", "app", "org.zealdocs.Zeal"),
        "/var/lib/flatpak/app/org.zealdocs.Zeal")]
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if env.get(var):
            sub = ("Programs", "Zeal") if var == "LOCALAPPDATA" else ("Zeal",)
            checks.append(("Zeal", os.path.join(env[var], *sub, "zeal.exe")))
    found: List[Tuple[str, str]] = []
    for app, path in checks:
        if path and os.path.exists(path) and app not in [a for a, _ in found]:
            found.append((app, path))
    exe = shutil.which("zeal", path=env.get("PATH", ""))
    if exe and "Zeal" not in [a for a, _ in found]:
        found.append(("Zeal", exe))
    return found


def _search_folders(env) -> List[Tuple[str, str, int]]:
    """Every folder docshelf looks in, existing or not: (folder, source,
    depth), in priority order."""
    home = _home(env)
    data = env.get("XDG_DATA_HOME") or _join(home, ".local", "share")
    out: List[Tuple[str, str, int]] = []
    for d in (env.get("DOCSHELF_DOCSET_DIRS") or "").split(os.pathsep):
        if d.strip():
            out.append((d.strip(), "folder", 2))
    candidates = [
        (env.get("DASHT_DOCSETS_DIR"), "folder"),
        (_join(data or "", "dasht", "docsets"), "folder"),
        *[(p, "zeal") for p in _zeal_custom_paths(env, viewer_apps(env))],
        (_join(data or "", "Zeal", "Zeal", "docsets"), "zeal"),
        (_join(home, ".local", "share", "Zeal", "Zeal", "docsets"), "zeal"),
        (_join(home, ".var", "app", "org.zealdocs.Zeal", "data", "Zeal", "Zeal",
               "docsets"), "zeal"),
        (_join(home, "Library", "Application Support", "Zeal", "Zeal", "docsets"),
         "zeal"),
        (_join(env.get("LOCALAPPDATA", ""), "Zeal", "Zeal", "docsets"), "zeal"),
        (_join(home, "Library", "Application Support", "Dash", "DocSets"), "dash"),
    ]
    for folder, source in candidates:
        if folder:
            out.append((folder, source, 2))
    for pkg in _dash_windows_packages(env):
        out.append((pkg, "dash", 4))
    seen, result = set(), []
    for folder, source, depth in out:  # one physical folder, one entry
        key = os.path.normcase(os.path.realpath(folder))
        if key not in seen:
            seen.add(key)
            result.append((folder, source, depth))
    return result


def docset_folders(env) -> List[Tuple[str, str]]:
    """Existing docset folders, in priority order: (folder, source)."""
    return [(f, s) for f, s, _ in _search_folders(env) if os.path.isdir(f)]


def _docset_dirs(root, depth):
    """*.docset folders directly in root, and down to `depth` levels."""
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


def _scan(env):
    """(folder, source, [docset paths]) for each existing folder."""
    return [(f, s, list(_docset_dirs(f, d)))
            for f, s, d in _search_folders(env) if os.path.isdir(f)]


def _open_all(cfg, env):
    """Open the docsets; return (docvols, {winner name: shadowed paths})."""
    docvols, by_name = [], {}
    for folder, source, paths in _scan(env):
        for path in paths:
            name = os.path.basename(path)[:-len(".docset")]
            if name in by_name:
                same = os.path.realpath(path) == os.path.realpath(by_name[name].path)
                if not same:
                    by_name[name].shadowed.append(path)
                continue
            d = open_docset(path, source, cfg.cache_dir)
            if d is not None:
                by_name[name] = d
                docvols.append(d)
    return docvols


def installed_docsets(cfg, env=None) -> List[DashDocvol]:
    """Docsets found in the known folders; the first folder wins a name."""
    return _open_all(cfg, os.environ if env is None else env)


def where_lines(cfg, env=None) -> List[str]:
    """The 'docset folders:' and 'apps:' lines of `where`."""
    env = os.environ if env is None else env
    docsets = {d.path: d for d in installed_docsets(cfg, env)}
    lines = ["docset folders:"]
    shown = False
    for folder, source, depth in _search_folders(env):
        shown = True
        if not os.path.isdir(folder):
            lines.append("  %s (missing)" % folder)
            continue
        paths = list(_docset_dirs(folder, depth))
        lines.append("  %s [%s] (found %d)" % (folder, source, len(paths)))
        for p in paths:
            d = docsets.get(os.path.abspath(p))
            for sh in (d.shadowed if d else []):
                lines.append("    shadowed: %s (%s) by %s" % (
                    os.path.basename(sh)[:-len(".docset")], sh, d.path))
    if not shown:
        lines.append("  none")
    apps = viewer_apps(env)
    lines.append("apps: " + (", ".join("%s (%s)" % a for a in apps)
                             if apps else "none found"))
    return lines
