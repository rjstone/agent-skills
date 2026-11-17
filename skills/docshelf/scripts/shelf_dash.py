"""docshelf Dash backend: read-only access to Dash/Zeal docsets."""
import hashlib
import json
import os
import pathlib
import plistlib
import re
import shutil
import sqlite3
from typing import List, Optional, Tuple
from urllib.parse import unquote

from shelf_core import CLIError, Docvol, Entry, resolve_doc_path, warn

INDEX_REL = ("Contents", "Resources", "docSet.dsidx")
DOCS_REL = ("Contents", "Resources", "Documents")
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

    def page_html(self, page: str) -> str:
        with open(self._doc_file(page), "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    def resolve_href(self, page: str, href: str) -> Optional[str]:
        target, frag = resolve_doc_path(page, href)
        try:
            self._doc_file(target)
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
