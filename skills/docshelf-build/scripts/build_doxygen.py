"""Doxygen HTML sites: read the client-side search index (search/*.js) or,
without one, menudata.js and the typed index pages, into InvEntry rows that
the Sphinx plan/build path already knows how to use."""
import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from build_inventory import InvEntry


class DoxygenFormatError(ValueError):
    """An index file that is not the JavaScript Doxygen writes."""


_BLOCKED = ("got an HTML page instead of a Doxygen index file; the site may be "
            "blocking automated requests")
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_INT = re.compile(r"-?\d+")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


class _Reader:
    """Recursive-descent reader for the literal subset Doxygen writes:
    arrays, objects (quoted or bare keys), strings, integers, booleans."""

    def __init__(self, text: str, pos: int):
        self.text, self.pos = text, pos

    def fail(self, what: str) -> DoxygenFormatError:
        return DoxygenFormatError("%s at offset %d" % (what, self.pos))

    def skip(self) -> None:
        t = self.text
        while self.pos < len(t):
            c = t[self.pos]
            if c.isspace():
                self.pos += 1
            elif t.startswith("/*", self.pos):
                end = t.find("*/", self.pos + 2)
                if end < 0:
                    raise self.fail("unterminated comment")
                self.pos = end + 2
            elif t.startswith("//", self.pos):
                end = t.find("\n", self.pos)
                self.pos = len(t) if end < 0 else end + 1
            else:
                return

    def peek(self) -> str:
        self.skip()
        if self.pos >= len(self.text):
            raise self.fail("unexpected end")
        return self.text[self.pos]

    def value(self) -> object:
        c = self.peek()
        if c == "[":
            return self.array()
        if c == "{":
            return self.obj()
        if c in "'\"":
            return self.string()
        m = _INT.match(self.text, self.pos)
        if m:
            self.pos = m.end()
            return int(m.group())
        for word, val in (("true", True), ("false", False)):
            if self.text.startswith(word, self.pos):
                self.pos += len(word)
                return val
        raise self.fail("unexpected %r" % c)

    def _items(self, close: str, item) -> None:
        self.pos += 1
        if self.peek() == close:
            self.pos += 1
            return
        while True:
            item()
            c = self.peek()
            self.pos += 1
            if c == close:
                return
            if c != ",":
                raise self.fail("expected ',' or %r" % close)
            if self.peek() == close:  # trailing comma
                self.pos += 1
                return

    def array(self) -> list:
        out: list = []
        self._items("]", lambda: out.append(self.value()))
        return out

    def obj(self) -> dict:
        out: dict = {}

        def item():
            c = self.peek()
            if c in "'\"":
                key = self.string()
            else:
                m = _IDENT.match(self.text, self.pos) or _INT.match(self.text, self.pos)
                if not m:
                    raise self.fail("bad key")
                key, self.pos = m.group(), m.end()
            if self.peek() != ":":
                raise self.fail("expected ':'")
            self.pos += 1
            out[key] = self.value()
        self._items("}", item)
        return out

    def string(self) -> str:
        t, quote = self.text, self.text[self.pos]
        i, out = self.pos + 1, []
        while i < len(t):
            c = t[i]
            if c == quote:
                self.pos = i + 1
                return "".join(out)
            if c == "\\":
                if i + 1 >= len(t):
                    break
                n = t[i + 1]
                if n == "u":
                    try:
                        out.append(chr(int(t[i + 2:i + 6], 16)))
                    except ValueError:
                        raise self.fail("bad \\u escape")
                    i += 6
                    continue
                out.append(_ESCAPES.get(n, n))
                i += 2
                continue
            if c == "\n":
                break
            out.append(c)
            i += 1
        raise self.fail("unterminated string")


def js_value(text: str, var: str) -> object:
    """The literal assigned by `var <var> = ...` in a Doxygen .js file."""
    if text.lstrip().startswith("<"):
        raise DoxygenFormatError(_BLOCKED)
    m = re.search(r"\bvar\s+%s\s*=" % re.escape(var), text)
    if not m:
        raise DoxygenFormatError("no 'var %s =' in the file" % var)
    return _Reader(text, m.end()).value()


Getter = Callable[[str], Optional[bytes]]

# search-index category (indexSectionNames) -> role; other categories get
# "doxygen:" + their label
CATEGORY_ROLES: Dict[str, str] = {
    "classes": "doxygen:Class", "namespaces": "doxygen:Namespace", "files": "doxygen:File",
    "functions": "doxygen:Function", "related": "doxygen:Function",
    "variables": "doxygen:Variable", "typedefs": "doxygen:Type", "enums": "doxygen:Enum",
    "enumvalues": "doxygen:Constant", "defines": "doxygen:Macro",
    "properties": "doxygen:Property", "groups": "doxygen:Module", "pages": "std:doc",
}
# read first: their names are scopes that must not qualify member names
_SCOPE_CATEGORIES = ("files", "groups", "pages")
_FILE_EXT = re.compile(r"\.\w{1,4}$")


@dataclass
class DoxyIndex:
    kind: str                                   # "search" or "menu"
    entries: List[InvEntry] = field(default_factory=list)
    files: List[Tuple[str, bytes]] = field(default_factory=list)  # (rel, body), read order
    warnings: List[str] = field(default_factory=list)


def page_uri(url: str, base_rel: str) -> str:
    """A site-relative uri (with any #anchor) for a link found in a file at
    base_rel ("search/" for search files, "" for pages at the root)."""
    root = "http://doxygen.invalid/"
    full = urllib.parse.urljoin(root + base_rel, url)
    return full[len(root):] if full.startswith(root) else url


def _strip_params(sig: str) -> str:
    """"ns::f(int (*g)(int)) const" -> "ns::f": cut at the "(" matching the
    last ")"."""
    end = sig.rfind(")")
    if end < 0:
        return sig.strip()
    depth = 0
    for i in range(end, -1, -1):
        if sig[i] == ")":
            depth += 1
        elif sig[i] == "(":
            depth -= 1
            if depth == 0:
                return sig[:i].strip()
    return sig.strip()


def member_name(display: str, scope: str, role: str, non_scopes: Set[str]) -> Tuple[str, str]:
    """(name, dispname) for an index entry. Qualified only when the scope is
    a class, struct, union or namespace; a file, group or page scope (C
    functions, macros, globals) keeps the bare name."""
    display, scope = html.unescape(display).strip(), html.unescape(scope).strip()
    if not scope or scope in non_scopes or _FILE_EXT.search(scope):
        return display, "-"
    if "(" in scope or scope.endswith(display):
        name = _strip_params(scope)
        return name, (scope if scope != name else "-")
    return scope + "::" + display, "-"


def _role(category: str, label: str, uri: str) -> str:
    role = CATEGORY_ROLES.get(category) or "doxygen:" + re.sub(r"\s+", "", label or category)
    if role == "doxygen:Class" and uri.startswith(("struct", "union")):
        return "doxygen:Struct"
    return role


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def read_search_index(get: Getter) -> DoxyIndex:
    """Entries from search/searchdata.js and the per-category, per-letter
    search/<name>_<hex>.js files (never all_*). A missing or unreadable
    letter file is a warning; a missing searchdata.js or no entries at all
    is a DoxygenFormatError."""
    idx = DoxyIndex("search")
    data = get("search/searchdata.js")
    if data is None:
        raise DoxygenFormatError("no search/searchdata.js")
    text = _decode(data)
    letters = js_value(text, "indexSectionsWithContent")
    names = js_value(text, "indexSectionNames")
    try:
        labels = js_value(text, "indexSectionLabels")
    except DoxygenFormatError:
        labels = {}
    if not isinstance(letters, dict) or not isinstance(names, dict):
        raise DoxygenFormatError("search/searchdata.js: unexpected layout")
    idx.files.append(("search/searchdata.js", data))
    cats = sorted((int(k), str(v)) for k, v in names.items() if str(k).isdigit())
    cats.sort(key=lambda c: (c[1] not in _SCOPE_CATEGORIES, c[0]))
    non_scopes: Set[str] = set()
    seen: Set[Tuple[str, str, str]] = set()
    for num, name in cats:
        if name == "all":
            continue
        label = str(labels.get(str(num), name)) if isinstance(labels, dict) else name
        for i in range(len(str(letters.get(str(num), "")))):
            rel = "search/%s_%x.js" % (name, i)
            body = get(rel)
            if body is None:
                idx.warnings.append("%s: missing" % rel)
                continue
            try:
                rows = js_value(_decode(body), "searchData")
            except DoxygenFormatError as e:
                idx.warnings.append("%s: %s" % (rel, e))
                continue
            idx.files.append((rel, body))
            for row in rows if isinstance(rows, list) else []:
                _add_row(idx, row, name, label, non_scopes, seen)
    if not idx.entries:
        raise DoxygenFormatError("the search index lists no entries")
    return idx


def _add_row(idx: DoxyIndex, row, category: str, label: str, non_scopes: Set[str],
             seen: Set[Tuple[str, str, str]]) -> None:
    """One searchData row: ['key', ['display', [url, flag, scope], ...]]."""
    if not (isinstance(row, list) and len(row) == 2 and isinstance(row[1], list) and row[1]):
        return
    display, links = row[1][0], row[1][1:]
    if not isinstance(display, str):
        return
    for link in links:
        if not (isinstance(link, list) and link and isinstance(link[0], str)):
            continue
        uri = page_uri(link[0], "search/")
        scope = link[2] if len(link) > 2 and isinstance(link[2], str) else ""
        role = _role(category, label, uri)
        if category in _SCOPE_CATEGORIES:
            name, disp = html.unescape(display).strip(), "-"
            non_scopes.add(name)
        else:
            name, disp = member_name(display, scope, role, non_scopes)
        if (name, role, uri) in seen:
            continue
        seen.add((name, role, uri))
        idx.entries.append(InvEntry(name, role, 1, uri, disp))
