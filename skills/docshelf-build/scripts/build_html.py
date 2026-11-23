"""Sphinx page HTML to docvol HTML: the main content only, links rewritten to
docvol page names, and stub pages for what is not stored."""
import html as htmllib
import posixpath
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple

from build_inventory import anchor_id

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
STUB_CLASS = "docshelf-build-stub"  # marks pages that hold no stored content
DROP = {"script", "style", "nav", "noscript", "template", "iframe", "form", "button",
        "head", "title", "link", "meta"}

Attrs = List[Tuple[str, Optional[str]]]
# a token: ("start", tag, attrs) | ("end", tag, None) | ("text", text, None)
Token = Tuple[str, str, Optional[Attrs]]


class _Tokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[Token] = []

    def handle_starttag(self, tag, attrs):
        self.out.append(("start", tag, attrs))
        if tag in VOID:
            self.out.append(("end", tag, None))

    def handle_startendtag(self, tag, attrs):
        self.out.append(("start", tag, attrs))
        self.out.append(("end", tag, None))

    def handle_endtag(self, tag):
        if tag not in VOID:
            self.out.append(("end", tag, None))

    def handle_data(self, data):
        self.out.append(("text", data, None))


def _tokens(text: str) -> List[Token]:
    p = _Tokens()
    p.feed(text)
    p.close()
    return p.out


def _attr(attrs: Attrs, name: str) -> Optional[str]:
    return next((v for k, v in attrs if k == name), None)


def _classes(attrs: Attrs) -> List[str]:
    return (_attr(attrs, "class") or "").split()


def _element_end(tokens: List[Token], start: int) -> int:
    """Index just past the end tag matching tokens[start] (or the end)."""
    tag, depth = tokens[start][1], 0
    for i in range(start, len(tokens)):
        kind, t, _ = tokens[i]
        if t == tag and kind == "start":
            depth += 1
        elif t == tag and kind == "end":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(tokens)


# selectors for the main content, in order (Read the Docs, Furo, Alabaster,
# PyData, plain HTML5)
_SELECTORS: List[Callable[[str, Attrs], bool]] = [
    lambda tag, a: _attr(a, "role") == "main",
    lambda tag, a: tag == "main",
    lambda tag, a: tag == "article",
    lambda tag, a: tag == "div" and "body" in _classes(a),
    lambda tag, a: tag == "body",
]


_SCRIPT_URL = re.compile(r"(?:javascript|vbscript|data):", re.I)


def _unsafe_attr(name: str, value: Optional[str]) -> bool:
    """An event handler (on*) or an href/src that runs script or embeds data."""
    name = name.lower()
    if name.startswith("on"):
        return True
    if name in ("href", "src") and value is not None:
        cleaned = "".join(c for c in value if not c.isspace() and ord(c) >= 32 and ord(c) != 127)
        return bool(_SCRIPT_URL.match(cleaned))
    return False


def _serialize(tokens: List[Token], href: Optional[Callable[[str], str]] = None) -> str:
    out: List[str] = []
    skip = 0   # depth inside a dropped element
    for i, (kind, t, attrs) in enumerate(tokens):
        if skip:
            if kind == "start" and t not in VOID:
                skip += 1
            elif kind == "end" and t not in VOID:
                skip -= 1
            continue
        if kind == "text":
            out.append(htmllib.escape(t, quote=False))
        elif kind == "start":
            if t in DROP or (t == "a" and "headerlink" in _classes(attrs)):
                skip = 1 if t not in VOID else 0
                continue
            if t == "img":
                alt = _attr(attrs, "alt")
                if alt:
                    out.append(htmllib.escape(alt, quote=False))
                continue
            parts = [t]
            for k, v in attrs:
                if _unsafe_attr(k, v):
                    continue
                if k == "href" and v is not None and href is not None:
                    v = href(v)
                elif k == "id" and v is not None:
                    v = anchor_id(v)
                parts.append(k if v is None else '%s="%s"' % (k, htmllib.escape(v)))
            out.append("<%s>" % " ".join(parts))
        else:  # end
            if t in VOID or t == "img":
                continue
            out.append("</%s>" % t)
    return "".join(out)


_DOXYGEN_CHROME = {"dynheader", "dyncontent", "ttc", "navpath"}


def _find(tokens: List[Token], tag: str, cls: str) -> Optional[int]:
    for i, (kind, t, attrs) in enumerate(tokens):
        if kind == "start" and t == tag and cls in _classes(attrs or []):
            return i
    return None


def _doxygen_content(tokens: List[Token]) -> Optional[List[Token]]:
    """For a Doxygen page (one with div.contents): the inner tokens of
    div.headertitle and div.contents, without graphs, tooltips, image maps
    and "More..." links. None for other pages."""
    start = _find(tokens, "div", "contents")
    if start is None:
        return None
    out: List[Token] = []
    title = _find(tokens, "div", "headertitle")
    if title is not None and title < start:
        out.extend(tokens[title + 1:_element_end(tokens, title) - 1])
    body = tokens[start + 1:_element_end(tokens, start) - 1]
    i = 0
    while i < len(body):
        kind, t, attrs = body[i]
        if kind == "start" and (t == "map" or (t == "div" and _DOXYGEN_CHROME & set(_classes(attrs or [])))):
            i = _element_end(body, i)
            continue
        if kind == "start" and t == "a":
            end = _element_end(body, i)
            text = "".join(x[1] for x in body[i + 1:end] if x[0] == "text").strip()
            if text == "More...":
                i = end
                continue
        out.append(body[i])
        i += 1
    return out


def main_content(page_html: str, doxygen: bool = False) -> str:
    """The page's main content as clean HTML: no navigation, sidebars,
    scripts, styles, header-link pilcrows or images (images become their alt
    text)."""
    tokens = _tokens(page_html)
    # only for Doxygen sites: older Sphinx (docutils < 0.18) also writes a
    # div.contents, for its local table of contents
    dox = _doxygen_content(tokens) if doxygen else None
    if dox is not None:
        return _serialize(dox).strip()
    for match in _SELECTORS:
        for i, (kind, t, attrs) in enumerate(tokens):
            if kind == "start" and match(t, attrs or []):
                inner = tokens[i + 1:_element_end(tokens, i) - 1]
                return _serialize(inner).strip()
    return _serialize(tokens).strip()


def _key_for(path: str, keys_by_uri: Dict[str, str]) -> Optional[str]:
    for cand in (path, path + "index.html" if path == "" or path.endswith("/") else None,
                 path[:-len("index.html")] if path.endswith("index.html") else None):
        if cand is not None and cand in keys_by_uri:
            return keys_by_uri[cand]
    return None


def rewrite_links(content: str, page_key: str, page_uri: str, keys_by_uri: Dict[str, str],
                  live_base: Optional[str]) -> str:
    """Links to pages in the docvol become paths relative to page_key's folder
    (as docshelf resolves them); other links into the site become live URLs
    when live_base is known; external links and same-page anchors stay."""
    fake = "http://docshelf-build.invalid/"
    here = posixpath.dirname(page_key) or "."

    def href(value: str) -> str:
        if value.startswith("#"):
            return "#" + anchor_id(urllib.parse.unquote(value[1:]))
        target = urllib.parse.urljoin(fake + page_uri, value)
        parts = urllib.parse.urlsplit(target)
        if parts.scheme + "://" + parts.netloc + "/" != fake:
            return value
        path = urllib.parse.unquote(parts.path[1:])
        frag = "#" + parts.fragment if parts.fragment else ""
        key = _key_for(path, keys_by_uri)
        if key is not None:
            local = "#" + anchor_id(urllib.parse.unquote(parts.fragment)) if parts.fragment else ""
            return posixpath.relpath(key, here) + local
        if live_base:
            return urllib.parse.urljoin(live_base, parts.path[1:]) + frag
        return value

    return _serialize(_tokens(content), href=href)


class _Headings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[Tuple[int, str, str]] = []
        self._cur: Optional[Tuple[int, str, List[str]]] = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3") and self._cur is None:
            hid = _attr(attrs, "id")
            if hid:
                self._cur = (int(tag[1]), hid, [])

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[2].append(data)

    def handle_endtag(self, tag):
        if self._cur is not None and tag == "h%d" % self._cur[0]:
            level, hid, parts = self._cur
            self.out.append((level, hid, " ".join("".join(parts).split())))
            self._cur = None


def headings(content: str) -> List[Tuple[int, str, str]]:
    """(level, id, text) of the h2 and h3 headings that have an id, in
    document order."""
    p = _Headings()
    p.feed(content)
    p.close()
    return p.out


def _url_candidates(url: str) -> List[str]:
    """Spellings under which a page URL may be stored: with or without
    .md/.mdx, and a trailing "/" or "/index"."""
    seen: List[str] = []

    def add(u: str) -> None:
        if u not in seen:
            seen.append(u)

    add(url)
    base = url
    for ext in (".mdx", ".md"):
        if base.endswith(ext):
            base = base[:-len(ext)]
            add(base)
            break
    add(base + ".md")
    for u in list(seen):
        if u.endswith("/"):
            add(u + "index")
            add(u + "index.md")
        if u.endswith("/index"):
            add(u[:-5])
    return seen


def rewrite_url_links(content: str, page_key: str, page_url: str,
                      keys_by_url: Dict[str, str], main_host: str) -> str:
    """Links to pages in the docvol become paths relative to page_key's
    folder; every other link becomes an absolute URL (so a relative link to
    a page that is not stored is live), external ones unchanged. main_host
    is the site's host (kept for callers; resolution needs only page_url)."""
    here = posixpath.dirname(page_key) or "."

    def href(value: str) -> str:
        if value.startswith("#"):
            return "#" + anchor_id(urllib.parse.unquote(value[1:]))
        if urllib.parse.urlsplit(value).scheme not in ("", "http", "https"):
            return value  # mailto:, tel: ...
        target = urllib.parse.urljoin(page_url, value)
        parts = urllib.parse.urlsplit(target)
        bare = urllib.parse.urlunsplit(parts._replace(fragment=""))
        for cand in _url_candidates(bare):
            if cand in keys_by_url:
                frag = anchor_id(urllib.parse.unquote(parts.fragment))
                return posixpath.relpath(keys_by_url[cand], here) + ("#" + frag if frag else "")
        return value if urllib.parse.urlsplit(value).scheme else target

    return _serialize(_tokens(content), href=href)


def stub_html(title: str, section: Optional[str], description: Optional[str],
              url: Optional[str], note: Optional[str]) -> str:
    """A page that is not stored: its title, section, description and where
    to read it (or why there is nowhere)."""
    e = htmllib.escape
    out = ['<div class="%s">' % STUB_CLASS, "<h1>%s</h1>" % e(title)]
    if section:
        out.append("<p>Section: %s</p>" % e(section))
    if description:
        out.append("<p>%s</p>" % e(description))
    if url:
        why = " (%s)" % e(note) if note else ""
        out.append('<p>Not stored%s; read it at <a href="%s">%s</a>.</p>'
                   % (why, e(url), e(url)))
    else:
        out.append("<p>Not stored: %s.</p>" % e(note or "no source address"))
    out.append("</div>")
    return "".join(out)
