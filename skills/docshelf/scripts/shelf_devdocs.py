"""docshelf DevDocs backend: docsets on disk, byte-span page index."""
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from shelf_core import CLIError, Config, Docset, Entry

DERIVED = ".docshelf"


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
        if i >= n or data[i] == 0x7D:  # }
            break
        if data[i] != 0x22:
            raise ValueError("unexpected byte at %d" % i)
        kend = string_end(i)
        key = json.loads(data[i:kend].decode("utf-8"))
        i = kend
        while data[i] in b" \t\r\n:":
            i += 1
        if data[i] != 0x22:
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


def _warn(msg):
    print("warning: " + msg, file=sys.stderr)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class DevDocsDocset(Docset):
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
        alias = meta.get("alias")
        self.aliases = (alias,) if alias else ()
        self.mtime = int(meta.get("mtime") or 0)
        self.db_path = os.path.join(folder, "db.json")
        self._entries: Optional[List[Entry]] = None
        self._index: Optional[Dict[str, Tuple[int, int]]] = None
        self.entry_count = len(self.entries())

    def data_dir(self) -> str:
        return os.path.join(self.folder, DERIVED)

    def entries(self) -> List[Entry]:
        if self._entries is None:
            idx = _load(os.path.join(self.folder, "index.json"))
            out = []
            for e in idx.get("entries", []):
                path = e["path"]
                page, _, anchor = path.partition("#")
                out.append(Entry(e["name"], e.get("type", ""),
                                 "%s:%s" % (self.name, path), page,
                                 anchor or None))
            self._entries = out
        return self._entries

    def _db_stat(self):
        try:
            st = os.stat(self.db_path)
        except OSError:
            raise CLIError("docset %s: db.json is missing" % self.name, 5)
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
                raise CLIError("docset %s: bad db.json: %s" % (self.name, e), 5)
            try:
                os.makedirs(self.data_dir(), exist_ok=True)
                tmp = cache + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"db_size": size, "db_mtime": mtime,
                               "pages": {k: list(v) for k, v in index.items()}}, f)
                os.replace(tmp, cache)
            except OSError as e:
                _warn("cannot write %s: %s" % (cache, e))
        self._index, self._idx_stat = index, (size, mtime)
        return index

    def pages(self) -> List[str]:
        return list(self.page_index())

    def page_html(self, page: str) -> str:
        span = self.page_index().get(page)
        if span is None:
            raise CLIError("no page %r in %s" % (page, self.name), 5)
        return read_span(self.db_path, span)

    def resolve(self, rest: str) -> Tuple[str, Optional[str], Optional[Entry]]:
        page, _, anchor = rest.partition("#")
        ref = "%s:%s" % (self.name, rest)
        entry = next((e for e in self.entries() if e.ref == ref), None)
        return page, anchor or None, entry

    def make_ref(self, page: str, anchor: Optional[str]) -> str:
        return "%s:%s%s" % (self.name, page, "#" + anchor if anchor else "")

    def stamp(self) -> str:
        return "%d|%d" % (self.mtime, self._db_stat()[0])


def installed_docsets(cfg: Config) -> List[DevDocsDocset]:
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
            out.append(DevDocsDocset(folder))
        except (OSError, ValueError, KeyError, TypeError) as e:
            _warn("skipping %s: %s" % (folder, e))
    return out
