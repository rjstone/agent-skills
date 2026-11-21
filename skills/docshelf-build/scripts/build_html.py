"""Sphinx page HTML to docvol HTML: the main content only, links rewritten to
docvol page names, and stub pages for what is not stored."""
import html as htmllib
import posixpath
import urllib.parse
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
STUB_CLASS = "docshelf-build-stub"  # marks pages that hold no stored content
DROP = {"script", "style", "nav", "noscript", "template", "iframe", "form", "button"}

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
                if k == "href" and v is not None and href is not None:
                    v = href(v)
                parts.append(k if v is None else '%s="%s"' % (k, htmllib.escape(v)))
            out.append("<%s>" % " ".join(parts))
        else:  # end
            if t in VOID or t == "img":
                continue
            out.append("</%s>" % t)
    return "".join(out)


def main_content(page_html: str) -> str:
    """The page's main content as clean HTML: no navigation, sidebars,
    scripts, styles, header-link pilcrows or images (images become their alt
    text)."""
    tokens = _tokens(page_html)
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
            return value
        target = urllib.parse.urljoin(fake + page_uri, value)
        parts = urllib.parse.urlsplit(target)
        if parts.scheme + "://" + parts.netloc + "/" != fake:
            return value
        path = urllib.parse.unquote(parts.path[1:])
        frag = "#" + parts.fragment if parts.fragment else ""
        key = _key_for(path, keys_by_uri)
        if key is not None:
            return posixpath.relpath(key, here) + frag
        if live_base:
            return urllib.parse.urljoin(live_base, parts.path[1:]) + frag
        return value

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
