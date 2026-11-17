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
import time
import zlib
from datetime import datetime
from typing import List, NamedTuple, Optional, Tuple
from urllib.parse import unquote, urlsplit

from shelf_core import CLIError, Docvol, Entry, make_temp, resolve_doc_path, warn

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
# A repeated footer is a run of trailing blocks that most pages end with
# exactly (copyright, links to the same few pages, a generator line); a
# repeated header is the same near the start of pages ("Skip to main content",
# navigation): at block 0, or at block 1 after one leading block that differs
# per page (MDN pages start with their own <title> text), which is kept. Only
# an exact repeat counts, so real docs are never guessed away. Both are kept on one page (the docset's index page, else the first
# entry's page) and left out of every other page, for show, the full-text
# index and the headings index.
REPEAT_SAMPLE = 40      # pages sampled, evenly spaced
REPEAT_MIN_PAGES = 5    # fewer pages: no detection
REPEAT_SHARE = 0.6      # share of sampled pages that must start/end with it
REPEAT_MAX_BLOCKS = 30
REPEAT_HEADER_STARTS = (0, 1)  # block indexes a header may start at
REPEAT_FORMAT = 3       # bump when repeats.json changes (2: header, 3: start)
_FAMILY_VERSION = re.compile(r"[_-](\d+(?:\.\d+)*)$")
_SQLITE_MAGIC = b"SQLite format 3\x00"


def dash_family(name: str) -> str:
    """'Python_3' -> 'python', 'Node.js' -> 'node.js', 'Qt_6.5' -> 'qt'."""
    return _FAMILY_VERSION.sub("", name.lower().replace(" ", "_"))


def name_version(name: str) -> str:
    """The version part dash_family strips: 'Python_3' -> '3',
    'Qt_6.5' -> '6.5', 'Node.js' -> ''."""
    m = _FAMILY_VERSION.search(name.replace(" ", "_"))
    return m.group(1) if m else ""


def _write_json(path: str, data) -> None:
    """Write data to path atomically (temp file + os.replace)."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = make_temp(folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def entry_location(path: str) -> Tuple[str, Optional[str]]:
    """Index path -> (page file, anchor or None): marker tags dropped, file
    decoded, backslashes turned into '/'."""
    path = re.sub(r"<dash_entry_[^>]*>", "", path)
    file_part, sep, anchor = path.partition("#")
    return unquote(file_part).replace("\\", "/"), (anchor if sep and anchor else None)


def _open_ro(path: str) -> sqlite3.Connection:
    # mode=ro, never immutable=1: a WAL index keeps its rows in the -wal file,
    # which immutable=1 ignores. Only for rollback-journal files: a mode=ro
    # reader of a WAL file still creates and writes its -shm file.
    uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


class Repeats(NamedTuple):
    """A docset's repeated header (at header_start) and footer block texts,
    and the page that keeps them."""
    header_start: int = 0
    header: List[str] = []
    footer: List[str] = []
    keep: Optional[str] = None


def _is_wal(path: str) -> bool:
    """True for a WAL-mode SQLite file: a -wal file beside it, or header
    bytes 18-19 (write/read version) equal to 2."""
    if os.path.exists(path + "-wal"):
        return True
    with open(path, "rb") as f:
        head = f.read(20)
    return len(head) == 20 and 2 in (head[18], head[19])


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
        self.shadowed: List[str] = []  # later copies of this name (`where`)
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
        # Dash on macOS writes no meta.json: then the name's version part.
        self.version = str(meta.get("version") or "") or name_version(self.name)
        self.release = self.version
        self.docs_dir = os.path.join(self.path, *DOCS_REL)
        self.index_file = os.path.join(self.path, *INDEX_REL)
        self._entries: Optional[List[Entry]] = None
        self._pages: Optional[List[str]] = None
        self._repeats: Optional[Repeats] = None
        self._count: Optional[int] = None
        self._copied: set = set()  # data_dir() subfolders copied this run
        # Discovery reads no rows (counting or copying a big index on every
        # command is slow): only the header, to skip a file that is no SQLite.
        with open(self.index_file, "rb") as f:
            if f.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
                raise ValueError("docSet.dsidx is not an SQLite database")

    def data_dir(self) -> str:
        digest = hashlib.sha1(self.path.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self.cache_dir, "docsets", "%s-%s" % (self.name, digest))

    def _copy_if_wal(self, path: str, sub: str) -> str:
        """path itself for a rollback-journal database. A WAL-mode one
        (header bytes 18-19 are 2, or a -wal file beside it) is read from a
        copy in data_dir()/sub instead, because SQLite writes a -shm file
        beside any WAL database it reads, and docshelf never writes into a
        docset. The copy (with the -wal) is refreshed only when stamp()
        changes: files are copied to temporary names and moved into place,
        and the stamp is written last, so a crash leaves no half copy that
        looks current."""
        if not _is_wal(path):
            return path
        dest_dir = os.path.join(self.data_dir(), sub)
        dest = os.path.join(dest_dir, os.path.basename(path))
        stamp_file = os.path.join(dest_dir, "stamp")
        stamp = self.stamp()
        if sub in self._copied or (os.path.isfile(dest)
                                   and _load_json(stamp_file).get("stamp") == stamp):
            return dest
        os.makedirs(dest_dir, exist_ok=True)
        moves = []
        try:
            for suffix in ("", "-wal"):
                if os.path.exists(path + suffix):
                    fd, tmp = make_temp(dest_dir)
                    os.close(fd)
                    moves.append((tmp, dest + suffix))
                    shutil.copyfile(path + suffix, tmp)
            for old in (stamp_file, dest + "-wal", dest + "-shm"):
                if os.path.exists(old):
                    os.remove(old)
            for tmp, final in moves:
                os.replace(tmp, final)
        finally:
            for tmp, _ in moves:
                if os.path.exists(tmp):
                    os.remove(tmp)
        _write_json(stamp_file, {"stamp": stamp})
        self._copied.add(sub)
        return dest

    def _open_db(self, path: str, sub: str) -> sqlite3.Connection:
        """Open a docset database: read-only in place, or (WAL mode) an
        ordinary open of our own copy (see _copy_if_wal)."""
        db = self._copy_if_wal(path, sub)
        return sqlite3.connect(db) if db != path else _open_ro(path)

    def _connect(self) -> "_Conn":
        """Open the index (docSet.dsidx); see _open_db."""
        return _Conn(self._open_db(self.index_file, "index"))

    def _index_error(self, e: Exception) -> CLIError:
        return CLIError("cannot read the index of docset %s (%s): %s"
                        % (self.name, self.path, e), 7)

    @property
    def entry_count(self) -> int:
        """Rows in the index, read only when asked for and cached in
        data_dir()/count.json under stamp(); 0 (with a warning) when the
        index cannot be read."""
        if self._count is None:
            cache = os.path.join(self.data_dir(), "count.json")
            stamp = self.stamp()
            data = _load_json(cache)
            if data.get("stamp") == stamp and isinstance(data.get("count"), int):
                self._count = data["count"]
                return self._count
            try:
                with self._connect() as con:
                    self._count = int(con.execute(
                        "SELECT COUNT(*) FROM %s" % _table(con)).fetchone()[0])
            except (sqlite3.Error, ValueError, OSError) as e:
                warn(str(self._index_error(e)))
                self._count = 0
                return 0
            try:
                _write_json(cache, {"stamp": stamp, "count": self._count})
            except OSError as e:
                warn("cannot write %s: %s" % (cache, e))
        return self._count

    def entries(self) -> List[Entry]:
        if self._entries is None:
            try:
                self._entries = self._read_entries()
            except (sqlite3.Error, ValueError, OSError) as e:
                raise self._index_error(e)
        return self._entries

    def _read_entries(self) -> List[Entry]:
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
        return out

    def pages(self) -> List[str]:
        if self._pages is None:
            self._pages = list(dict.fromkeys(e.page for e in self.entries()))
        return self._pages

    def _doc_file(self, page: str) -> str:
        """The page's file; CLIError 5 when it is missing or resolves (through
        '..' or a symlink) to a file outside Documents/."""
        docs = os.path.realpath(self.docs_dir)
        full = os.path.realpath(os.path.join(docs, *page.split("/")))
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
            with _Conn(self._open_db(idx, "tarix")) as con:
                row = con.execute("SELECT path FROM tarindex WHERE path LIKE "
                                  "'%.docset/%' LIMIT 1").fetchone()
                if not row:
                    return None
                prefix = row[0][:row[0].index(".docset/") + len(".docset/")]
                row = con.execute("SELECT hash FROM tarindex WHERE path = ?",
                                  (prefix + rel,)).fetchone()
        except (sqlite3.Error, ValueError, OSError) as e:
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

    def _index_page(self) -> Optional[str]:
        try:
            with open(os.path.join(self.path, "Contents", "Info.plist"), "rb") as f:
                value = plistlib.load(f).get("dashIndexFilePath")
        except Exception:  # unreadable or malformed plist: no index page
            return None
        return entry_location(value)[0] if isinstance(value, str) and value else None

    def detect_repeats(self) -> Repeats:
        """The repeated header and footer; Repeats() if neither repeats."""
        pages = self.pages()
        if len(pages) < REPEAT_MIN_PAGES:
            return Repeats()
        step = max(1, len(pages) // REPEAT_SAMPLE)
        heads: dict = {}
        tails: dict = {}
        sampled = 0
        for page in pages[::step][:REPEAT_SAMPLE]:
            try:
                texts = [b.text for b in super().page_blocks(page)]
            except (CLIError, OSError, ValueError):
                continue
            sampled += 1
            # a whole page is never a header or footer: one block is left
            for k in range(1, min(REPEAT_MAX_BLOCKS, len(texts) - 1) + 1):
                key = tuple(texts[-k:])
                tails[key] = tails.get(key, 0) + 1
            for start in REPEAT_HEADER_STARTS:
                for k in range(1, min(REPEAT_MAX_BLOCKS, len(texts) - 1 - start) + 1):
                    key = (start, tuple(texts[start:start + k]))
                    heads[key] = heads.get(key, 0) + 1
        if sampled < REPEAT_MIN_PAGES:
            return Repeats()
        need = max(REPEAT_MIN_PAGES, REPEAT_SHARE * sampled)
        # the longest run; on a tie the earlier start
        start, header = max((k for k, c in heads.items() if c >= need),
                            key=lambda k: (len(k[1]), -k[0]), default=(0, ()))
        footer = max((k for k, c in tails.items() if c >= need), key=len, default=())
        if not header and not footer:
            return Repeats()
        index = self._index_page()
        return Repeats(start if header else 0, list(header), list(footer),
                       index if index in pages else pages[0])

    def repeats_info(self) -> Repeats:
        """detect_repeats, cached in <data_dir>/repeats.json."""
        if self._repeats is not None:
            return self._repeats
        stamp = "%s|repeats%d" % (self.stamp(), REPEAT_FORMAT)
        cache = os.path.join(self.data_dir(), "repeats.json")
        data = _load_json(cache)
        if data.get("stamp") == stamp and isinstance(data.get("header"), list) \
                and isinstance(data.get("footer"), list) \
                and data.get("header_start") in REPEAT_HEADER_STARTS:
            self._repeats = Repeats(data["header_start"], data["header"],
                                    data["footer"], data.get("keep"))
            return self._repeats
        found = self.detect_repeats()
        try:
            _write_json(cache, dict(found._asdict(), stamp=stamp))
        except OSError as e:
            warn("cannot write %s: %s" % (cache, e))
        self._repeats = found
        return self._repeats

    def page_blocks(self, page: str, link=None):
        """The page's blocks without the docset's repeated header and footer
        (both kept on one page). A page is never emptied: the footer goes
        only when blocks remain, the header only when blocks remain after
        both."""
        blocks = super().page_blocks(page, link)
        rep = self.repeats_info()
        if page == rep.keep or not (rep.header or rep.footer):
            return blocks
        # Compare the plain text: link=... appends " [REF]" to link text.
        plain = blocks if link is None else super().page_blocks(page)
        texts = [b.text for b in plain] if len(plain) == len(blocks) \
            else [b.text for b in blocks]
        end = len(blocks)
        nf, nh, s0 = len(rep.footer), len(rep.header), rep.header_start
        if nf and end > nf and texts[-nf:] == rep.footer:
            end -= nf
        if nh and end - nh > 0 and s0 + nh <= end \
                and texts[s0:s0 + nh] == rep.header:
            return blocks[:s0] + blocks[s0 + nh:end]
        return blocks[:end]

    def resolve_href(self, page: str, href: str) -> Optional[str]:
        for decode in (True, False):  # a file name may hold a literal %XX
            target, frag = resolve_doc_path(page, href, decode)
            if self._has_page(target):
                return self.make_ref(target, frag)
        return None

    def _has_page(self, target: str) -> bool:
        try:
            self._doc_file(target)
        except CLIError:
            try:
                return self._tarix_row(self._tarix_rel(target)) is not None
            except CLIError:
                return False
        return True

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
        res = os.path.join(self.path, "Contents", "Resources")
        tarix_index = os.path.join(res, "tarixIndex.db")
        for f in (self.index_file, self.index_file + "-wal",
                  os.path.join(res, "tarix.tgz"), tarix_index, tarix_index + "-wal"):
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
# Every location comes from the env mapping given, never from the process,
# except the fixed system paths below and the Windows registry.

# Fixed app locations no variable controls: (app, path).
SYSTEM_APP_PATHS: Tuple[Tuple[str, str], ...] = (
    ("Dash", "/Applications/Dash.app"),
    ("Dash", "/Applications/Setapp/Dash.app"),
    ("Zeal", "/Applications/Zeal.app"),
    ("Zeal", "/var/lib/flatpak/app/org.zealdocs.Zeal"),
)


def _no_system(env) -> bool:
    # Test hook: DOCSHELF_NO_SYSTEM_APPS=1 skips SYSTEM_APP_PATHS and the
    # registry, so tests never find a real Dash or Zeal install.
    return env.get("DOCSHELF_NO_SYSTEM_APPS") == "1"


def _zeal_registry_path() -> Optional[str]:
    """Zeal's docsets folder from the Windows registry, if set."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zeal\Zeal\docsets") as k:
            return str(winreg.QueryValueEx(k, "path")[0])
    except OSError:
        return None


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
    if not _no_system(env):
        out.append(_zeal_registry_path())
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
    checks = [] if _no_system(env) else list(SYSTEM_APP_PATHS)
    checks += [("Dash", _join(home, "Applications", "Dash.app"))]
    checks += [("Dash", p) for p in _dash_windows_packages(env)]
    checks += [("Zeal", _join(home, ".var", "app", "org.zealdocs.Zeal"))]
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
    """Open the docsets, the first of each name; later copies of a name go
    to the winner's `shadowed` list. Returns the list of docvols."""
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


# --- catalogs: which docsets Dash or Zeal could download --------------------
# docshelf never contacts kapeli.com or its mirrors: Kapeli asked that tools
# add no load to his servers (the user, 2026-11-16). Docset archives are served
# only from there, so docshelf downloads none: Dash and Zeal do. `sources`
# only lists docset names, to tell the user what the app can download.
# Names come from GitHub, one API request each (the API lists at most 1000
# entries of a folder). Official: the *.xml files at the root of the
# Kapeli/feeds repo (214 in 2026-11). Only the listing is read, never a feed
# file: those hold the kapeli.com download URLs. User-contributed: one folder
# per docset under docsets/ in Kapeli/Dash-User-Contributions (630 in 2026-11).
FEEDS_LIST_URL = "https://api.github.com/repos/Kapeli/feeds/contents/"
CONTRIB_LIST_URL = ("https://api.github.com/repos/Kapeli/Dash-User-Contributions"
                    "/contents/docsets")
# Zeal's combined catalog: a best-effort public service with no stability
# promise. Used only when the GitHub list fails and cached without its icons.
# Entries: {name, title, sourceId, versions, ...}; sourceId com.kapeli.dash =
# official, com.kapeli.contrib = user-contributed.
ZEAL_CATALOG_URL = "https://api.zealdocs.org/_api/v1/catalog.json"
CATALOG_MAX_AGE = 7 * 86400
# label: (cache key, GitHub listing URL, entry type, suffix, Zeal sourceId)
DOCSET_LISTS = {
    "official": ("feeds-list", FEEDS_LIST_URL, "file", ".xml", "com.kapeli.dash"),
    "user-contributed": ("contrib-list", CONTRIB_LIST_URL, "dir", "",
                         "com.kapeli.contrib"),
}
_ZEAL_KEY = "zeal-catalog"
_SOURCE_ERRORS = (CLIError, ValueError, KeyError, TypeError, AttributeError)


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", "_", name.strip().lower())


def catalogs_wanted(env) -> bool:
    """Dash or Zeal installed, or a docset folder present."""
    return bool(viewer_apps(env) or docset_folders(env))


def _catalog_path(cfg, key: str) -> str:
    return os.path.join(cfg.cache_dir, "docsets", "catalogs", key + ".json")


def _read_catalog(cfg, key: str, max_age=None):
    """The cached JSON under key, or None (missing, unreadable, too old)."""
    path = _catalog_path(cfg, key)
    try:
        if max_age is not None and not 0 <= time.time() - os.path.getmtime(path) < max_age:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_catalog(cfg, key: str, data) -> None:
    path = _catalog_path(cfg, key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = make_temp(os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        raise CLIError("cannot write the docset list in %s: %s (set "
                       "DOCSHELF_CACHE_DIR to a writable folder)"
                       % (os.path.dirname(path), e), 2)


def _github_names(body: bytes, kind: str, suffix: str) -> List[str]:
    """Sorted names of a GitHub folder listing's entries of type kind,
    minus suffix; others are left out."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("the GitHub listing is not a list")
    names = [str(i["name"]) for i in data if isinstance(i, dict)
             and i.get("type") == kind and str(i.get("name") or "").endswith(suffix)]
    return sorted(n[:len(n) - len(suffix)] for n in names if n != suffix)


def _slim_catalog(body: bytes) -> list:
    """Zeal's catalog without icons and other fields never read."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Zeal catalog is not a list")
    keep = ("name", "title", "sourceId", "versions")
    # Malformed entries are kept: label_names skips and counts them.
    return [{k: e.get(k) for k in keep if k in e} if isinstance(e, dict) else e
            for e in data]


def _first_version(e) -> str:
    """The first version of a Zeal entry; ValueError when versions is not a list."""
    versions = e.get("versions")
    if versions is None:
        return ""
    if not isinstance(versions, list):
        raise ValueError("versions is not a list")
    return next((str(v) for v in versions if v), "")


def _zeal_rows(cat, source_id: str):
    """((name, version, title) rows of one kind, number of malformed entries
    skipped) from Zeal's catalog; one bad entry never spoils the rest. An
    entry with no readable name has no kind: it is counted with the official
    list only, so the two lists never report it twice."""
    out, skipped = [], 0
    for e in cat:
        try:
            name = e["name"]
            if not isinstance(name, str) or not name:
                raise ValueError("no name")
        except _SOURCE_ERRORS:
            skipped += source_id == DOCSET_LISTS["official"][4]
            continue
        try:
            if e.get("sourceId") == source_id:
                out.append((name, _first_version(e), str(e.get("title") or "")))
        except _SOURCE_ERRORS:
            skipped += 1
    return out, skipped


def _cached_or_fetched(cfg, key: str, url: str, refresh: bool, slim):
    import shelf_devdocs
    if not refresh:
        data = _read_catalog(cfg, key, CATALOG_MAX_AGE)
        if data is not None:
            return data
    try:
        data = slim(shelf_devdocs.fetch(url))
    except shelf_devdocs.NetError:
        stale = _read_catalog(cfg, key)
        if stale is None:
            raise
        date = datetime.fromtimestamp(
            os.path.getmtime(_catalog_path(cfg, key))).strftime("%Y-%m-%d")
        print("note: using the cached docset list from %s (could not reach %s)"
              % (date, urlsplit(url).hostname or url), file=sys.stderr)
        return stale
    _write_catalog(cfg, key, data)
    return data


def label_names(cfg, label: str, refresh: bool = False,
                zeal: Optional[dict] = None) -> List[Tuple[str, str, str]]:
    """(name, version, title) of each docset of one kind: from GitHub (names
    only), from Zeal's catalog only when GitHub fails. CLIError(7) when both
    fail. zeal: a dict shared by the calls of one run, so Zeal's catalog is
    fetched (or found unreachable) at most once per run."""
    key, url, kind, suffix, source_id = DOCSET_LISTS[label]
    try:
        names = _cached_or_fetched(cfg, key, url, refresh,
                                   lambda b: _github_names(b, kind, suffix))
        return [(str(n), "", "") for n in names]
    except _SOURCE_ERRORS as first:
        if getattr(first, "code", 7) != 7:
            raise
        try:
            cat = _zeal_once(cfg, refresh, zeal if zeal is not None else {})
            out, skipped = _zeal_rows(cat, source_id)
        except _SOURCE_ERRORS as e:
            raise CLIError("cannot load the %s docset list (GitHub: %s; Zeal's "
                           "catalog: %s)" % (label, first, e), 7)
        print("note (no action needed): the %s list came from Zeal's catalog; "
              "GitHub was unreachable (%s)" % (label, first), file=sys.stderr)
        if skipped:
            print("note: skipped %d malformed entr%s in Zeal's catalog"
                  % (skipped, "y" if skipped == 1 else "ies"), file=sys.stderr)
        return out


def _zeal_once(cfg, refresh: bool, memo: dict):
    """Zeal's catalog, fetched or read at most once per memo; a failure is
    remembered and raised again rather than retried."""
    if "error" in memo:
        raise memo["error"]
    if "catalog" not in memo:
        try:
            memo["catalog"] = _cached_or_fetched(cfg, _ZEAL_KEY, ZEAL_CATALOG_URL,
                                                 refresh, _slim_catalog)
        except _SOURCE_ERRORS as e:
            memo["error"] = e
            raise
    return memo["catalog"]


def catalog_names(cfg, refresh: bool = False) -> List[Tuple[str, str, str, str]]:
    """(name, version, title, label) of every official and user-contributed
    docset; raises CLIError(7) when a kind cannot be loaded at all."""
    zeal: dict = {}
    return [(n, v, t, label) for label in DOCSET_LISTS
            for n, v, t in label_names(cfg, label, refresh, zeal)]


def cached_catalog_match(cfg, name: str) -> Optional[str]:
    """The docset name a cached catalog (any age; never the network) lists
    for name, compared by _norm; else None."""
    want = _norm(name)
    for label, (key, _u, _k, _s, source_id) in DOCSET_LISTS.items():
        names = _read_catalog(cfg, key)
        if isinstance(names, list):
            for n in names:
                if isinstance(n, str) and _norm(n) == want:
                    return n
    zeal = _read_catalog(cfg, _ZEAL_KEY)
    if isinstance(zeal, list):
        for e in zeal:
            if isinstance(e, dict) and isinstance(e.get("name"), str) \
                    and _norm(e["name"]) == want:
                return e["name"]
    return None
