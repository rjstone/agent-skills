"""Doxygen HTML sites: read the client-side search index (search/*.js) or,
without one, menudata.js and the typed index pages, into InvEntry rows that
the Sphinx plan/build path already knows how to use."""
import html
import re
from html.parser import HTMLParser
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from build_core import warn
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
    return _struct(role, uri)


def _struct(role: str, uri: str) -> str:
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


# ---- Reader 2: menudata.js and the index pages ----

LIST_PAGE_ROLES: Dict[str, str] = {
    "annotated.html": "doxygen:Class", "namespaces.html": "doxygen:Namespace",
    "files.html": "doxygen:File", "modules.html": "doxygen:Module",
    "topics.html": "doxygen:Module", "pages.html": "std:doc",
}
MEMBER_KIND_ROLES: Dict[str, str] = {
    "func": "doxygen:Function", "vars": "doxygen:Variable", "type": "doxygen:Type",
    "enum": "doxygen:Enum", "eval": "doxygen:Constant", "rela": "doxygen:Function",
    "prop": "doxygen:Property", "defs": "doxygen:Macro",
}
_MEMBER_PAGE = re.compile(r"^(functions|globals|namespacemembers)"
                          r"(?:_(func|vars|type|enum|eval|rela|prop|defs)(?=[_.]))?"
                          r"(?:_([^./]+))?\.html$")
# tried in order when a site has no menudata.js
_FIXED_PAGES = (["annotated.html", "namespaces.html", "files.html", "modules.html",
                 "topics.html", "pages.html"] +
                ["%s_%s.html" % (stem, kind)
                 for stem in ("functions", "globals", "namespacemembers")
                 for kind in MEMBER_KIND_ROLES if kind != "defs" or stem == "globals"])


def _page_role(rel: str) -> Optional[str]:
    """Role of the entries an index page lists; None for a page not read
    (untyped member pages are decided by menu_pages)."""
    if rel in LIST_PAGE_ROLES:
        return LIST_PAGE_ROLES[rel]
    m = _MEMBER_PAGE.match(rel)
    if m and m.group(2):
        return MEMBER_KIND_ROLES[m.group(2)]
    return None


def menu_pages(menu: dict) -> List[Tuple[str, str]]:
    """(rel, role) of every index page the menu links to, in menu order,
    fragments dropped, deduplicated; untyped member pages (functions.html,
    functions_a.html) only for a stem without typed tabs."""
    urls: List[str] = []

    def walk(node):
        if isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str):
                urls.append(url.split("#", 1)[0])
            walk(node.get("children"))
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(menu)
    typed = {m.group(1) for m in map(_MEMBER_PAGE.match, urls) if m and m.group(2)}
    out: List[Tuple[str, str]] = []
    for rel in urls:
        role = _page_role(rel)
        m = _MEMBER_PAGE.match(rel)
        if role is None and m and m.group(1) == "functions" and "functions" not in typed:
            role = "doxygen:Function"
        if role and (rel, role) not in out:
            out.append((rel, role))
    return out


class _Contents(HTMLParser):
    """Links inside div.contents: href, text, the <li> they sit in (with the
    text before its first link), and whether they sit in a directory
    table's entry cell."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.li: Optional[int] = None
        self.li_count = 0
        self.prefix: Dict[int, str] = {}
        self.linked: Set[int] = set()
        self.links: List[dict] = []
        self.a: Optional[dict] = None
        self.entry = False
        self.directory = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if self.depth == 0:
            if tag == "div" and "contents" in cls:
                self.depth = 1
            return
        if tag == "div":
            self.depth += 1
        elif tag == "li":
            self.li = self.li_count
            self.li_count += 1
            self.prefix[self.li] = ""
        elif tag == "table" and "directory" in cls:
            self.directory = True
        elif tag == "td" and "entry" in cls:
            self.entry = True
        elif tag == "a" and a.get("href"):
            self.a = {"href": a["href"], "text": "", "li": self.li, "entry": self.entry}
            if self.li is not None:
                self.linked.add(self.li)

    def handle_endtag(self, tag):
        if self.depth == 0:
            return
        if tag == "div":
            self.depth -= 1
        elif tag == "li":
            self.li = None
        elif tag == "td":
            self.entry = False
        elif tag == "a" and self.a is not None:
            self.a["text"] = self.a["text"].strip()
            self.links.append(self.a)
            self.a = None

    def handle_data(self, data):
        if self.depth == 0:
            return
        if self.a is not None:
            self.a["text"] += data
        elif self.li is not None and self.li not in self.linked:
            self.prefix[self.li] += data


def _contents(page_html: str) -> _Contents:
    p = _Contents()
    p.feed(page_html)
    p.close()
    return p


def _site_link(href: str) -> bool:
    return not href.startswith("#") and not re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I)


def parse_list_page(page_html: str, role: str) -> List[InvEntry]:
    """Entries of a list page (class list, files, groups, pages): the links in
    a directory table's entry cells, or every contents link without one."""
    p = _contents(page_html)
    links = [x for x in p.links if x["entry"]] if p.directory else p.links
    out = []
    for x in links:
        if _site_link(x["href"]) and x["text"]:
            uri = page_uri(x["href"], "")
            out.append(InvEntry(html.unescape(x["text"]), _struct(role, uri), 1, uri, "-"))
    return out


def parse_member_page(page_html: str, role: str, non_scopes: Set[str]) -> List[InvEntry]:
    """Entries of a member index page: each <li>name : <a>Owner</a>, ...</li>
    gives one entry per owner link."""
    p = _contents(page_html)
    out = []
    for x in p.links:
        if x["li"] is None or not _site_link(x["href"]):
            continue
        text = p.prefix.get(x["li"], "").strip().rstrip(":").strip()
        if text.endswith("()"):
            text = text[:-2].rstrip()
        if not text:
            continue
        name, disp = member_name(text, x["text"], role, non_scopes)
        out.append(InvEntry(name, role, 1, page_uri(x["href"], ""), disp))
    return out


def _letter_pages(page_html: str, rel: str) -> List[str]:
    """Per-letter pages of the same member index that rel's contents link
    to (stem[_kind]_<letter>.html)."""
    m = _MEMBER_PAGE.match(rel)
    if not m:
        return []
    out: List[str] = []
    for x in _contents(page_html).links:
        target = x["href"].split("#", 1)[0]
        t = _MEMBER_PAGE.match(target)
        if t and t.group(1) == m.group(1) and t.group(2) == m.group(2) and t.group(3) \
                and target not in out:
            out.append(target)
    return out


def read_menu_index(get: Getter, log: Callable[[str], None] = warn) -> DoxyIndex:
    """Entries from the index pages listed in menudata.js, or, without it,
    from fixed page names and the letter links found in them. List pages
    are read first: their file, group and page names keep member names
    bare. A page the menu lists but the site lacks is a warning; a fixed
    name the site lacks is not (most sites have only some of them)."""
    idx = DoxyIndex("menu")
    data = get("menudata.js")
    from_menu = data is not None
    if data is not None:
        idx.files.append(("menudata.js", data))
        menu = js_value(_decode(data), "menudata")
        pages = menu_pages(menu if isinstance(menu, dict) else {})
    else:
        pages = [(rel, _page_role(rel) or "") for rel in _FIXED_PAGES]
    pages.sort(key=lambda p: p[0] not in LIST_PAGE_ROLES)
    log("reading %d Doxygen index pages" % len(pages))
    non_scopes: Set[str] = set()
    seen: Set[Tuple[str, str, str]] = set()
    queue = list(pages)
    done: Set[str] = set()
    while queue:
        rel, role = queue.pop(0)
        if rel in done:
            continue
        done.add(rel)
        body = get(rel)
        if body is None:
            if from_menu:
                idx.warnings.append("%s: missing" % rel)
            continue
        idx.files.append((rel, body))
        text = _decode(body)
        if rel in LIST_PAGE_ROLES:
            found = parse_list_page(text, role)
            if role in ("doxygen:File", "doxygen:Module", "std:doc"):
                non_scopes.update(e.name for e in found)
        else:
            found = parse_member_page(text, role, non_scopes)
            queue.extend((r, role) for r in _letter_pages(text, rel) if r not in done)
        for e in found:
            if (e.name, e.role, e.uri) not in seen:
                seen.add((e.name, e.role, e.uri))
                idx.entries.append(e)
    if not idx.entries:
        raise DoxygenFormatError("no entries found in menudata.js or the Doxygen index pages")
    return idx
