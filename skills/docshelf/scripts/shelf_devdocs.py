"""docshelf DevDocs backend: docvols on disk, byte-span page index."""
import http.client
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from shelf_core import (VERSION, CLIError, warn, Config, Docvol, Entry, make_temp,
                        pick_docvol, sweep_stale_tmp)

DERIVED = ".docshelf"
MANIFEST_URL = "https://devdocs.io/docs.json"
DOCUMENTS_BASE = "https://documents.devdocs.io"
# Unambiguous on purpose: a server can filter or rate-limit by it.
USER_AGENT = "docshelf/" + VERSION
# DevDocs ends every page with a licence notice and the upstream URL; it is
# the same on every page but the URL, so it is left out of what we render.
_ATTRIBUTION = re.compile(
    r'<div class="_attribution">(?:(?!<div).)*?</div>\s*\Z', re.S)
MANIFEST_MAX_AGE = 86400
NET_TIMEOUT = 60
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._~+-]*$", re.IGNORECASE)
CHUNK = 1 << 20


def devdocs_dir(cfg: Config) -> str:
    return os.path.join(cfg.cache_dir, "devdocs")


def build_page_index(db_path: str) -> Dict[str, Tuple[int, int]]:
    """Byte spans (quotes included) of each string value in a flat JSON
    object {key: html}. Reads the file once; never builds the pages in
    memory as str. A string ends at the first quote preceded by an even
    number of backslashes (UTF-8 multibyte sequences contain neither)."""
    with open(db_path, "rb") as f:
        data = f.read()
    spans: Dict[str, Tuple[int, int]] = {}
    find = data.find
    n = len(data)

    def string_end(start):  # start is the opening quote; returns index after close
        i = start + 1
        while True:
            q = find(b'"', i)
            if q < 0:
                raise ValueError("unterminated string at byte %d" % start)
            k = q - 1
            while k > start and data[k] == 0x5C:
                k -= 1
            if (q - 1 - k) % 2 == 0:
                return q + 1
            i = q + 1

    i = find(b"{")
    if i < 0:
        raise ValueError("not a JSON object")
    i += 1
    while True:
        while i < n and data[i] in b" \t\r\n,":
            i += 1
        if i >= n:
            raise ValueError("truncated: no closing brace")
        if data[i] == 0x7D:  # }
            if data[i + 1:].strip(b" \t\r\n"):
                raise ValueError("unexpected data after the closing brace")
            break
        if data[i] != 0x22:
            raise ValueError("unexpected byte at %d" % i)
        kend = string_end(i)
        key = json.loads(data[i:kend].decode("utf-8"))
        i = kend
        while i < n and data[i] in b" \t\r\n:":
            i += 1
        if i >= n or data[i] != 0x22:
            raise ValueError("page %r is not a string" % key)
        vend = string_end(i)
        spans[key] = (i, vend)
        i = vend
    return spans


def read_span(db_path: str, span: Tuple[int, int]) -> str:
    with open(db_path, "rb") as f:
        f.seek(span[0])
        raw = f.read(span[1] - span[0])
    return json.loads(raw.decode("utf-8"))


_warn = warn


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class DevDocsDocvol(Docvol):
    def __init__(self, folder: str):
        self.folder = folder
        meta = _load(os.path.join(folder, "meta.json"))
        if not isinstance(meta, dict):
            raise ValueError("meta.json: expected an object")
        self.name = os.path.basename(folder)
        self.family = self.name.split("~")[0]
        self.release = str(meta.get("release") or "")
        base = meta.get("name") or self.family
        self.display_name = base
        version = str(meta.get("version") or "")
        if not version and "~" in self.name:
            version = self.name.split("~", 1)[1].replace("_", " ")
        self.title = ("%s %s" % (base, version)).strip()
        self.version = version
        self.source = "devdocs"
        alias = meta.get("alias")
        self.aliases = (alias,) if alias else ()
        self.mtime = int(meta.get("mtime") or 0)
        self.db_path = os.path.join(folder, "db.json")
        self._entries: Optional[List[Entry]] = None
        self._index: Optional[Dict[str, Tuple[int, int]]] = None
        if not os.path.isfile(os.path.join(folder, "index.json")):
            # a cheap check that reads nothing: installed_docvols() skips a
            # docvol without its index, entry_count or not
            raise OSError("index.json is missing")
        count = meta.get("entry_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            self.entry_count = count  # stored at install: index.json stays unread
        else:  # an install from before entry_count: count the index
            try:
                self.entry_count = len(self.entries())
            except CLIError as e:  # discovery skips a damaged docvol
                raise ValueError(str(e))

    def data_dir(self) -> str:
        return os.path.join(self.folder, DERIVED)

    def entries(self) -> List[Entry]:
        if self._entries is None:
            try:
                idx = _load(os.path.join(self.folder, "index.json"))
                if not isinstance(idx, dict) or not isinstance(
                        idx.get("entries", []), list):
                    raise ValueError("expected an object with an entries list")
                out = []
                for e in idx.get("entries", []):
                    path = e["path"]
                    page, _, anchor = path.partition("#")
                    out.append(Entry(e["name"], e.get("type", ""),
                                     "%s:%s" % (self.name, path), page,
                                     anchor or None))
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                # with entry_count the constructor no longer reads the index
                raise CLIError("docvol %s: damaged index.json (%s); reinstall "
                               "with: docshelf.py install %s"
                               % (self.name, e, self.name), 5)
            self._entries = out
        return self._entries

    def _db_stat(self):
        try:
            st = os.stat(self.db_path)
        except OSError:
            raise CLIError("docvol %s: db.json is missing" % self.name, 5)
        return st.st_size, int(st.st_mtime)

    def page_index(self) -> Dict[str, Tuple[int, int]]:
        size, mtime = self._db_stat()
        if self._index is not None and getattr(self, "_idx_stat", None) == (size, mtime):
            return self._index
        cache = os.path.join(self.data_dir(), "pages.json")
        index = None
        try:
            c = _load(cache)
            if c.get("db_size") == size and c.get("db_mtime") == mtime:
                index = {k: (v[0], v[1]) for k, v in c["pages"].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            pass
        if index is None:
            try:
                index = build_page_index(self.db_path)
            except ValueError as e:
                raise CLIError("docvol %s: damaged db.json (%s); reinstall with: "
                               "docshelf.py install %s" % (self.name, e, self.name), 5)
            self._write_page_index(index, size, mtime)
        self._index, self._idx_stat = index, (size, mtime)
        return index

    def _write_page_index(self, index, size, mtime) -> None:
        cache = os.path.join(self.data_dir(), "pages.json")
        try:
            os.makedirs(self.data_dir(), exist_ok=True)
            fd, tmp = make_temp(self.data_dir())
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"db_size": size, "db_mtime": mtime,
                               "pages": {k: list(v) for k, v in index.items()}}, f)
                os.replace(tmp, cache)
            except BaseException:
                _discard(tmp)
                raise
        except OSError as e:
            _warn("cannot write %s: %s" % (cache, e))

    def store_page_index(self, index) -> None:
        """Keep an index built elsewhere (install) for this db.json."""
        size, mtime = self._db_stat()
        self._write_page_index(index, size, mtime)
        self._index, self._idx_stat = index, (size, mtime)

    def pages(self) -> List[str]:
        return list(self.page_index())

    def page_html(self, page: str) -> str:
        span = self.page_index().get(page)
        if span is None:
            raise CLIError("no page %r in %s" % (page, self.name), 5)
        return _ATTRIBUTION.sub("", read_span(self.db_path, span))

    def resolve(self, rest: str) -> Tuple[str, Optional[str], Optional[Entry]]:
        page, _, anchor = rest.partition("#")
        ref = "%s:%s" % (self.name, rest)
        entry = next((e for e in self.entries() if e.ref == ref), None)
        return page, anchor or None, entry

    def make_ref(self, page: str, anchor: Optional[str]) -> str:
        return "%s:%s%s" % (self.name, page, "#" + anchor if anchor else "")

    def stamp(self) -> str:
        return "%d|%d" % (self.mtime, self._db_stat()[0])


def installed_docvols(cfg: Config) -> List[DevDocsDocvol]:
    root = devdocs_dir(cfg)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    out = []
    for n in names:
        folder = os.path.join(root, n)
        if not os.path.isdir(folder):
            continue
        try:
            out.append(DevDocsDocvol(folder))
        except (OSError, ValueError, KeyError, TypeError) as e:
            _warn("skipping %s: %s" % (folder, e))
    return out


# --- network ---------------------------------------------------------------
class NetError(CLIError):
    """A download failed (exit code 7); names the host to allow."""

    def __init__(self, url: str, reason: str, status: Optional[int] = None):
        self.status = status  # the HTTP status, when the server answered
        host = urlsplit(url).hostname or url
        super().__init__(
            "cannot reach %s (%s). The hosts docshelf may contact are listed "
            "in assets/allowlist.txt in the skill folder." % (host, reason), 7)


def _write_error(path: str, e: OSError) -> CLIError:
    return CLIError("cannot write %s: %s (check free disk space and that "
                    "DOCSHELF_CACHE_DIR is a writable folder)" % (path, e), 2)


def fetch(url: str, dest: Optional[str] = None) -> bytes:
    """GET url, redirects followed. With dest, stream the body to that file
    in chunks and return b""; else return the body."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
            if dest is None:
                return r.read()
            try:
                f = open(dest, "wb")
            except OSError as e:
                raise _write_error(dest, e)
            with f:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        return b""
                    try:
                        f.write(chunk)
                    except OSError as e:
                        raise _write_error(dest, e)
    except urllib.error.HTTPError as e:
        raise NetError(url, "HTTP %d" % e.code, status=e.code)
    except (urllib.error.URLError, OSError, ValueError,
            http.client.HTTPException) as e:
        raise NetError(url, str(getattr(e, "reason", e)))


def cached_manifest(cfg: Config) -> Optional[List[dict]]:
    """The cached DevDocs list at any age; None when missing or unreadable.
    Never fetches."""
    try:
        return _manifest_rows(_load(os.path.join(devdocs_dir(cfg), "docs.json")))
    except (OSError, ValueError):
        return None


def get_manifest(cfg: Config, refresh: bool = False) -> List[dict]:
    """The DevDocs documentation list, cached in <cache>/devdocs/docs.json for 24 h.
    If it cannot be fetched, a cached copy (any age) is used with a note."""
    path = os.path.join(devdocs_dir(cfg), "docs.json")
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        age = None
    if age is not None and not refresh and 0 <= age < MANIFEST_MAX_AGE:
        try:
            return _manifest_rows(_load(path))
        except (OSError, ValueError):
            pass
    try:
        try:
            rows = _manifest_rows(json.loads(fetch(MANIFEST_URL).decode("utf-8")))
        except ValueError as e:  # includes UnicodeDecodeError
            raise NetError(MANIFEST_URL, "not a DevDocs list: %s" % e)
    except NetError as net_err:
        if age is None:
            raise
        try:
            rows = _manifest_rows(_load(path))
        except (OSError, ValueError):
            raise net_err
        date = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
        print("note: using the cached DevDocs list from %s "
              "(could not reach devdocs.io)" % date, file=sys.stderr)
        return rows
    try:
        os.makedirs(devdocs_dir(cfg), exist_ok=True)
        fd, tmp = make_temp(devdocs_dir(cfg))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            _discard(tmp)
            raise
    except OSError as e:
        raise CLIError("cannot write the DevDocs list in %s: %s (set "
                       "DOCSHELF_CACHE_DIR to a writable folder)"
                       % (devdocs_dir(cfg), e), 2)
    return rows


def not_installed_message(cfg: Config, name: str, how) -> Optional[str]:
    """For a docvol name that isn't installed: when the cached DevDocs list
    (any age; never the network) has it, say so and how(slug) installs it."""
    try:
        row = resolve_install(_manifest_rows(_load(
            os.path.join(devdocs_dir(cfg), "docs.json"))), name)
    except (OSError, ValueError, CLIError):
        row = None
    if row is not None:
        return "docvol %r is not installed; DevDocs has it: %s" % (
            name, how(row["slug"]))
    import shelf_dash
    docset = shelf_dash.cached_catalog_match(cfg, name)
    if docset and shelf_dash.catalogs_wanted(os.environ):
        return ("docvol %r is not installed; Dash/Zeal can download docset "
                "%r (in the app); docshelf doesn't install docsets"
                % (name, docset))
    return None


def _manifest_rows(data) -> List[dict]:
    if not isinstance(data, list) or not all(
            isinstance(r, dict) and isinstance(r.get("slug"), str) for r in data):
        raise ValueError("expected a list of documentation rows")
    return data


def resolve_install(manifest: List[dict], name: str) -> dict:
    """The manifest row for name: exact slug, slug ignoring case, then alias,
    family or title (the first row: DevDocs lists newest first)."""
    low = name.lower()

    def first(test):
        return next((r for r in manifest if test(r)), None)

    found = (first(lambda r: r["slug"] == name)
             or first(lambda r: r["slug"].lower() == low)
             or first(lambda r: (r.get("alias") or "").lower() == low)
             or first(lambda r: r["slug"].split("~")[0].lower() == low)
             or first(lambda r: _titles(r) & {low}))
    if found:
        return found
    close = [r["slug"] for r in manifest
             if low in r["slug"].lower() or low in str(r.get("name", "")).lower()]
    msg = "no DevDocs documentation matches %r" % name
    if close:
        msg += "; close: " + ", ".join(close[:5])
    raise CLIError(msg + " (see: docshelf.py sources QUERY)", 5)


def _titles(row: dict) -> set:
    name = str(row.get("name") or "")
    version = str(row.get("version") or "")
    return {name.lower(), ("%s %s" % (name, version)).strip().lower()}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _discard(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


class NotOnDevDocs(CLIError):
    """documents.devdocs.io answered 404 for a slug (exit code 5)."""

    def __init__(self, slug: str, message: str = ""):
        self.slug = slug
        super().__init__(message or (
            "%s: documentation not found on DevDocs (HTTP 404 from %s); "
            "sources QUERY lists the names" % (slug, _documents_host())), 5)


def _documents_host() -> str:
    return urlsplit(DOCUMENTS_BASE).hostname or DOCUMENTS_BASE


def install(cfg: Config, row: dict) -> str:
    """Download row's documentation: 'installed', 'updated' or 'up to date'."""
    slug = row["slug"]
    if not SLUG_RE.match(slug):
        raise CLIError("refusing documentation slug %r: not a plain name" % slug, 2)
    folder = os.path.join(devdocs_dir(cfg), slug)
    meta_path = os.path.join(folder, "meta.json")
    status = "installed"
    try:
        old = _load(meta_path)
        status = "updated"
        if (int(old.get("mtime") or 0) >= int(row.get("mtime") or 0)
                and os.path.isfile(os.path.join(folder, "index.json"))
                and os.path.isfile(os.path.join(folder, "db.json"))):
            return "up to date"
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    created = not os.path.isdir(folder)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise CLIError("cannot create %s: %s (set DOCSHELF_CACHE_DIR to a "
                       "writable folder)" % (folder, e), 2)
    names = ("index.json", "db.json", "meta.json")
    tmps = {}
    pindex = None
    try:
        sweep_stale_tmp(folder)
        for n in names:
            fd, tmps[n] = make_temp(folder, prefix=n + ".", sweep=False)
            os.close(fd)
        for n in names[:2]:
            try:
                fetch("%s/%s/%s" % (DOCUMENTS_BASE, slug, n), tmps[n])
            except NetError as e:
                if e.status == 404:
                    raise NotOnDevDocs(slug)
                raise
        try:
            idx = _load(tmps["index.json"])
            if not isinstance(idx, dict) or not isinstance(
                    idx.get("entries"), list):
                raise ValueError("no entries list")
            pindex = build_page_index(tmps["db.json"])
        except (ValueError, AttributeError, UnicodeDecodeError) as e:
            raise NetError("%s/%s/" % (DOCUMENTS_BASE, slug),
                           "unexpected content: %s" % e)
        meta = {"slug": slug, "name": row.get("name") or slug,
                "release": str(row.get("release") or ""),
                "mtime": int(row.get("mtime") or 0),
                "installedAt": _utc_now(), "alias": row.get("alias") or None,
                "version": str(row.get("version") or ""),
                "entry_count": len(idx["entries"])}
        with open(tmps["meta.json"], "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        os.replace(tmps["index.json"], os.path.join(folder, "index.json"))
        os.replace(tmps["db.json"], os.path.join(folder, "db.json"))
        os.replace(tmps["meta.json"], meta_path)
    except BaseException:
        for t in tmps.values():
            _discard(t)
        if created:
            try:
                os.rmdir(folder)
            except OSError:
                pass
        raise
    DevDocsDocvol(folder).store_page_index(pindex)
    return status


def remove(cfg: Config, slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise CLIError("refusing documentation slug %r: not a plain name" % slug, 2)
    shutil.rmtree(os.path.join(devdocs_dir(cfg), slug))


# --- commands --------------------------------------------------------------
def _describe(cfg: Config, status: str, slug: str) -> str:
    d = DevDocsDocvol(os.path.join(devdocs_dir(cfg), slug))
    return "%s %s (%s %s, %d entries)" % (status, slug, d.display_name,
                                          d.release, d.entry_count)


def cmd_sources(cfg, args) -> int:
    rows = get_manifest(cfg, args.refresh)
    words = [w.lower() for w in args.query]
    have = {d.name for d in installed_docvols(cfg)}
    hits = [r for r in rows
            if all(w in r["slug"].lower() or w in str(r.get("name", "")).lower()
                   for w in words)]
    hits.sort(key=lambda r: (len(r["slug"]), r["slug"]))
    seen = set()
    unique = []
    for r in hits:  # a slug twice in the list: the first row, as in install
        if r["slug"] not in seen:
            seen.add(r["slug"])
            unique.append(r)
    hits = unique
    for r in hits[:30]:
        print("%s  %s  %s  %.1f MB%s" % (
            r["slug"], r.get("name", ""), r.get("release", ""),
            (r.get("db_size") or 0) / 1_000_000,
            "  (installed)" if r["slug"] in have else ""))
    if not hits:
        print("no DevDocs documentation matches %s" % " ".join(args.query))
    _print_catalog_hits(cfg, args, words)
    return 0


def _print_catalog_hits(cfg, args, words) -> None:
    """Dash/Zeal docset names matching the query, when an app or a docset
    folder exists; a failing list is a note, never an error."""
    import shelf_dash
    if not shelf_dash.catalogs_wanted(os.environ):
        return
    norm = [shelf_dash._norm(w) for w in words]
    here = {shelf_dash._norm(d.name): d.name
            for d in shelf_dash.installed_docsets(cfg)}
    zeal: dict = {}  # Zeal's catalog at most once per run
    for label in shelf_dash.DOCSET_LISTS:
        try:
            names = shelf_dash.label_names(cfg, label, args.refresh, zeal)
        except CLIError as e:
            print("note: the Dash/Zeal %s list could not be loaded (%s)"
                  % (label, e), file=sys.stderr)
            continue
        shown = 0
        for name, _v, title in sorted(names):
            key = shelf_dash._norm(name)
            if shown < 30 and all(w in key or w in shelf_dash._norm(title)
                                  for w in norm):
                shown += 1
                print("%s  (Dash/Zeal: download in the app, %s)%s" % (
                    name, label,
                    "  (here as %s)" % here[key] if key in here else ""))


def _row_version(row: dict) -> str:
    """A manifest row's version, as DevDocsDocvol derives it."""
    version = str(row.get("version") or "")
    slug = row["slug"]
    if not version and "~" in slug:
        version = slug.split("~", 1)[1].replace("_", " ")
    return version


class Redundant(CLIError):
    """The documentation is already on disk as a Dash/Zeal docset."""


def _refuse_redundant(cfg: Config, row: dict) -> None:
    import types
    import shelf_backends
    want = types.SimpleNamespace(family=row["slug"].split("~")[0],
                                 version=_row_version(row), read_only=False)
    for d in shelf_backends.installed_docvols(cfg):
        if d.read_only and shelf_backends.same_documentation(d, want):
            raise Redundant(
                "%s: skipped, Dash/Zeal docset %s has this documentation and "
                "is used as is; install --force %s downloads it anyway"
                % (row["slug"], d.name, row["slug"]), 2)


def _refuse_read_only(d: Docvol) -> None:
    if d.read_only:
        raise CLIError("%s is a Dash/Zeal docset; Dash or Zeal manages it"
                       % d.name, 2)


def _installed_note(cfg: Config, name: str) -> Optional[str]:
    """The line for a project-list name already on disk (any backend), or None."""
    import shelf_backends
    low = name.lower()
    hits = [d for d in shelf_backends.installed_docvols(cfg)
            if low in (d.name.lower(), d.family.lower())]
    if any(not d.read_only for d in hits):
        return "%s: installed" % name
    if hits:
        return "%s: Dash/Zeal docset %s, not installed from DevDocs" % (
            name, hits[0].name)
    return None


def _each(items, action) -> int:
    """Run action on each item, printing the line it returns; a Redundant is
    a skip note. Every failure is kept, and one CLIError joins them all (one
    per line) with the first failure's code once all items have run."""
    failures = []
    for item in items:
        try:
            line = action(item)
        except Redundant as e:
            print(str(e), file=sys.stderr)  # a skip, not a failure
            continue
        except CLIError as e:
            failures.append(e)
            continue
        if line:
            print(line)
    if failures:
        raise CLIError("\n".join(str(e) for e in failures), failures[0].code)
    return 0


def cmd_install(cfg, args) -> int:
    names = list(args.names or [])
    from_project = not names
    if from_project:
        names = list(cfg.project_docvols)
        if not names:
            raise CLIError('install needs NAME (or a "docvols" list in '
                           '.docshelf.json)', 2)
    rows = get_manifest(cfg)

    def one(name: str) -> Optional[str]:
        if from_project:
            note = _installed_note(cfg, name)
            if note:
                return note
        row = resolve_install(rows, name)
        if not getattr(args, "force", False):
            _refuse_redundant(cfg, row)
        return _describe(cfg, install(cfg, row), row["slug"])
    return _each(names, one)


def cmd_update(cfg, args) -> int:
    import shelf_backends
    have = shelf_backends.installed_docvols(cfg)
    if args.names:
        targets = [pick_docvol(have, n) for n in args.names]
        for d in targets:
            _refuse_read_only(d)
    else:
        targets = [d for d in have if not d.read_only]
    if not targets:
        if have:
            print("no DevDocs docvols to update (Dash/Zeal docsets are updated "
                  "in Dash or Zeal)")
        else:
            print("no docvols installed (install NAME; sources QUERY finds names)")
        return 0
    rows = get_manifest(cfg, refresh=True)
    by_slug = {}
    for r in rows:
        by_slug.setdefault(r["slug"], r)  # first row wins, as in install

    def one(d) -> Optional[str]:
        row = by_slug.get(d.name)
        if row is None:
            _warn("%s is no longer in the DevDocs list; skipped" % d.name)
            return None
        try:
            return _describe(cfg, install(cfg, row), d.name)
        except NotOnDevDocs as e:
            raise NotOnDevDocs(e.slug, "DevDocs no longer has documents for "
                               "%s (HTTP 404 from %s); the installed copy is "
                               "kept" % (e.slug, _documents_host()))
    return _each(targets, one)


def cmd_remove(cfg, args) -> int:
    import shelf_backends
    try:
        found = pick_docvol(shelf_backends.installed_docvols(cfg), args.name)
        _refuse_read_only(found)
        name = found.name
    except CLIError as e:
        if e.code == 2:
            raise
        name = _unloadable_folder(cfg, args.name)
        if e.code != 5 or name is None:
            raise
    remove(cfg, name)
    print("removed %s (notes untouched)" % name)
    return 0


def _unloadable_folder(cfg: Config, name: str) -> Optional[str]:
    """The docvol folder called name (or whose meta.json slug is name) that
    installed_docvols skipped as damaged; None if there is none."""
    root = devdocs_dir(cfg)
    try:
        folders = sorted(os.listdir(root))
    except OSError:
        return None
    for n in folders:
        if not os.path.isdir(os.path.join(root, n)):
            continue
        try:
            slug = _load(os.path.join(root, n, "meta.json")).get("slug")
        except (OSError, ValueError, AttributeError):
            slug = None
        if n == name or slug == name:
            return n
    return None
