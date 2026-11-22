"""llms.txt sources: parse an index, derive page keys, walk sub-indexes.

Stdlib only. No network here: callers pass `get_text` (URL -> text) and
optionally `read_file` (path -> text) so tests and the fetcher stay separate.
"""
import hashlib
import os
from collections import Counter
from typing import Callable, Dict, List, NamedTuple, Optional, Set, Tuple
from urllib.parse import unquote, urljoin, urlsplit

from build_core import CLIError, warn
from build_fetch import FetchError

MAX_DEPTH = 3  # sub-index levels below the root (root = depth 0)
PAGE_SUFFIXES = (".md", ".mdx", ".html", ".htm")


class Link(NamedTuple):
    title: str
    url: str
    note: Optional[str]
    section: Optional[str]


class LlmsPage(NamedTuple):
    key: str
    url: str
    title: str
    section: Optional[str]
    description: Optional[str]


class Tree(NamedTuple):
    title: str
    main_host: str
    pages: List[LlmsPage]
    indexes: List[dict]
    sha256: str


def _balanced(s: str, start: int, open_c: str, close_c: str) -> int:
    """Index of the bracket closing s[start] (which is open_c), or -1."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == open_c:
            depth += 1
        elif s[i] == close_c:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _parse_link_line(line: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """(title, href, note) for a `- [title](url): note` line, else None."""
    s = line.lstrip()
    if len(s) < 3 or s[0] not in "-*+" or s[1] not in " \t":
        return None
    s = s[1:].lstrip()
    if not s.startswith("["):
        return None
    end = _balanced(s, 0, "[", "]")
    if end < 0 or s[end + 1:end + 2] != "(":
        return None
    close = _balanced(s, end + 1, "(", ")")
    if close < 0:
        return None
    href = s[end + 2:close].strip()
    if not href:
        return None
    rest = s[close + 1:].strip()
    note = rest[1:].strip() if rest.startswith(":") else ""
    return s[1:end].strip(), href, note or None


def parse_index(text: str, index_url: str) -> Tuple[str, List[Link]]:
    """(H1 title or "", links) of an llms.txt; URLs made absolute."""
    text = text.lstrip("\ufeff").replace("\r", "")
    title = ""
    section: Optional[str] = None
    links: List[Link] = []
    for line in text.split("\n"):
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            section = line[3:].strip() or None
        else:
            got = _parse_link_line(line)
            if got:
                t, href, note = got
                try:
                    url = urljoin(index_url, href)
                    ok = urlsplit(url).scheme in ("http", "https")
                except ValueError as e:
                    warn("link skipped (%s): %s" % (e, href))
                    continue
                if ok:
                    links.append(Link(t, url, note, section))
    return title, links


def _join(*names: Optional[str]) -> Optional[str]:
    """Section path "a / b", skipping empty parts; None when all are empty."""
    return " / ".join(n for n in names if n) or None


def is_llms_source(arg: str) -> bool:
    """True for an http(s) URL whose path ends .txt, or an existing local .txt file."""
    parts = urlsplit(arg)
    if parts.scheme in ("http", "https"):
        return parts.path.lower().endswith(".txt")
    return arg.lower().endswith(".txt") and os.path.isfile(arg)


WELL_KNOWN_TXT = ("robots.txt", "humans.txt", "security.txt", "ads.txt", "app-ads.txt")


def _is_well_known(url: str) -> bool:
    """A site-metadata .txt file (robots.txt ...), never an index."""
    return urlsplit(url).path.rsplit("/", 1)[-1].lower() in WELL_KNOWN_TXT


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def url_key(url: str, main_host: str) -> str:
    """Page key: the URL path without extension, safe as a relative path."""
    parts = urlsplit(url)
    path = unquote(parts.path).replace("\\", "/")
    segs: List[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if segs:
                segs.pop()
            continue
        segs.append(seg)
    if path.endswith("/") or not segs:
        segs.append("index")
    else:
        last = segs[-1]
        for suf in PAGE_SUFFIXES:
            if last.lower().endswith(suf):
                last = last[:-len(suf)]
                break
        if last:
            segs[-1] = last
        else:
            segs[-1] = "index"
    key = "/".join(segs)
    host = _host(url)
    if host == main_host:
        return key
    return ("_" if host in ("", ".", "..") else host) + "/" + key


def _read_local(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def read_tree(source: str, get_text: Callable[[str], str],
              read_file: Callable[[str], str] = _read_local) -> Tree:
    """Walk an llms.txt and its same-host sub-indexes into a page list."""
    local = urlsplit(source).scheme not in ("http", "https")
    raw: List[str] = []
    indexes: List[dict] = []
    pages: List[Tuple[str, str, Optional[str], Optional[str]]] = []  # url, title, section, desc
    seen_keys: Set[str] = set()
    visited: Set[str] = {source}

    if local:
        try:
            root_text = read_file(source)
        except OSError as e:
            raise CLIError("cannot read %s: %s" % (source, e.strerror or e), 2)
    else:
        root_text = get_text(source)
    raw.append(root_text)
    root_title, root_links = parse_index(root_text, source)
    if local:
        hosts = Counter(_host(lk.url) for lk in root_links
                        if not urlsplit(lk.url).path.lower().endswith(".txt"))
        if not hosts:  # only sub-indexes listed: their host is the site's
            hosts = Counter(_host(lk.url) for lk in root_links
                            if not _is_well_known(lk.url))
        main_host = hosts.most_common(1)[0][0] if hosts else ""
    else:
        main_host = _host(source)

    def walk(url: str, title: str, links: List[Link], parent: Optional[str],
             section: Optional[str], depth: int) -> None:
        entry = {"url": url, "title": title, "pages": 0, "parent": parent, "note": None}
        indexes.append(entry)
        for lk in links:
            if _is_well_known(lk.url):
                continue
            if urlsplit(lk.url).path.lower().endswith(".txt"):
                if lk.url in visited:
                    continue
                visited.add(lk.url)
                sub = {"url": lk.url, "title": lk.title, "pages": None,
                       "parent": url, "note": None}
                if _host(lk.url) != main_host:
                    sub["note"] = "other host, not followed"
                    indexes.append(sub)
                elif urlsplit(lk.url).path.rsplit("/", 1)[-1].lower().endswith("-full.txt"):
                    sub["note"] = "full text, not followed"
                    indexes.append(sub)
                elif depth + 1 > MAX_DEPTH:
                    sub["note"] = "depth limit"
                    indexes.append(sub)
                else:
                    try:
                        text = get_text(lk.url)
                    except (CLIError, FetchError) as e:
                        reason = e.reason if isinstance(e, FetchError) else str(e)
                        warn("sub-index %s skipped: %s" % (lk.url, reason))
                        sub["note"] = "fetch failed: " + reason
                        indexes.append(sub)
                        continue
                    raw.append(text)
                    sub_title, sub_links = parse_index(text, lk.url)
                    name = sub_title or lk.title
                    sub_section = _join(section, lk.section, name)
                    walk(lk.url, name, sub_links, url, sub_section, depth + 1)
                continue
            key = url_key(lk.url, main_host)
            if key in seen_keys:  # same key = same page; first listed wins
                continue
            seen_keys.add(key)
            pages.append((lk.url, lk.title, _join(section, lk.section), lk.note))
            entry["pages"] += 1

    walk(source, root_title, root_links, None, None, 0)
    if not pages:
        raise CLIError("no page links found in " + source +
                       " (is it an llms.txt index?)", 3)

    out = [LlmsPage(url_key(url, main_host), url, title, section, desc)
           for url, title, section, desc in pages]
    digest = hashlib.sha256("".join(raw).encode("utf-8")).hexdigest()
    return Tree(root_title, main_host, out, indexes, digest)
