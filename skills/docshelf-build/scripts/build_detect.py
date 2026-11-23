"""Which build type a site or local folder supports, from the files present:
objects.inv (Sphinx) or llms.txt. Sphinx wins when both are there: its
inventory types every API entry and separates reference from guides."""
import os
import urllib.parse
from typing import Callable, List, NamedTuple, Optional, Tuple

from build_archive import find_source_archive
from build_fetch import FetchError, looks_html, normalize_source, open_url_source
from build_llms import parse_index

SPHINX_MAGIC = b"# Sphinx inventory version"
DOCS = {"sphinx": "BUILD-sphinx.md", "llms": "BUILD-llmstxt.md", "doxygen": "BUILD-doxygen.md"}


class Detection(NamedTuple):
    kind: Optional[str]            # "sphinx", "llms" or None
    source: Optional[str]          # the SOURCE to give plan/build
    found: List[Tuple[str, str]]   # (kind, where) of every usable index found
    tried: List[Tuple[str, str]]   # (URL or path, why it was not used)
    archive: Optional[str] = None  # URL of the site's HTML archive (Sphinx URL only)
    index: Optional[str] = None    # Doxygen: "search" or "menu"


def _doxygen_folders(inv: str, is_url: bool) -> List[str]:
    """The folder that would hold objects.inv, then its parent: where a
    Doxygen site's search/ folder or menudata.js may be. URL folders end in
    "/", local ones do not."""
    if is_url:
        folder = inv[:-len("objects.inv")]
        parts = urllib.parse.urlsplit(folder)
        out = [folder]
        if parts.path.rstrip("/"):
            parent = parts.path.rstrip("/").rsplit("/", 1)[0] + "/"
            out.append(urllib.parse.urlunsplit((parts.scheme, parts.netloc, parent, "", "")))
        return out
    folder = os.path.dirname(inv)
    parent = os.path.dirname(folder)
    return [folder] + ([parent] if parent != folder else [])


def _is_llms(text: str, where: str) -> bool:
    if looks_html(text):
        return False
    try:
        return bool(parse_index(text, where)[1])
    except ValueError:
        return False


def _candidates(src: str) -> Tuple[List[str], List[str], bool]:
    """(objects.inv candidates, llms.txt candidates, is_url)."""
    if src.startswith(("http://", "https://")):
        parts = urllib.parse.urlsplit(src)
        last = parts.path.rsplit("/", 1)[-1]
        explicit_txt = last.lower().endswith(".txt")
        if explicit_txt or last == "objects.inv":
            folder = urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path[:-len(last)], "", ""))
        else:
            folder = normalize_source(src)[0]
        root = "%s://%s/" % (parts.scheme, parts.netloc)
        llms = [src.split("#", 1)[0]] if explicit_txt else []
        for c in (folder + "llms.txt", root + "llms.txt"):
            if c not in llms:
                llms.append(c)
        return [folder + "objects.inv"], llms, True
    path = os.path.realpath(src)
    folder = os.path.dirname(path) if os.path.isfile(path) else path
    llms = [path] if path.lower().endswith(".txt") and os.path.isfile(path) else []
    if os.path.join(folder, "llms.txt") not in llms:
        llms.append(os.path.join(folder, "llms.txt"))
    return [os.path.join(folder, "objects.inv")], llms, False


def detect(src: str, opener=None, sleep: Optional[Callable[[float], None]] = None) -> Detection:
    """Look for objects.inv and llms.txt at src (a URL or local path) and
    pick the build type: Sphinx first, then llms.txt, else none."""
    invs, llmss, is_url = _candidates(src)
    fetch = open_url_source(opener=opener, sleep=sleep, delay=0.2) if is_url else None
    tried: List[Tuple[str, str]] = []

    def read(where: str) -> Optional[bytes]:
        if fetch is not None:
            try:
                return fetch.get_url(where)
            except FetchError as e:
                tried.append((where, e.reason))
                return None
        try:
            with open(where, "rb") as f:
                return f.read()
        except OSError:
            tried.append((where, "missing"))
            return None

    found: List[Tuple[str, str]] = []
    for where in invs:
        body = read(where)
        if body is not None and body.startswith(SPHINX_MAGIC):
            found.append(("sphinx", where))
        elif body is not None:
            tried.append((where, "not a Sphinx inventory"))
    for where in llmss:
        body = read(where)
        if body is not None and _is_llms(body.decode("utf-8", "replace"), where):
            found.append(("llms", where))
            break
        if body is not None:
            tried.append((where, "not an llms.txt page list"))
    index = None
    for folder in _doxygen_folders(invs[0], is_url):
        def at(rel: str) -> str:
            return folder + rel if is_url else os.path.join(folder, *rel.split("/"))
        body = read(at("search/searchdata.js"))
        if body is not None and b"indexSectionNames" in body:
            found.append(("doxygen", folder))
            index = "search"
            break
        body = read(at("menudata.js"))
        if body is not None and b"var menudata" in body:
            found.append(("doxygen", folder))
            index = "menu"
            break
    if not found:
        return Detection(None, None, found, tried)
    kind, where = found[0]
    if kind == "doxygen":
        return Detection(kind, where, found, tried, None, index)
    if kind == "sphinx":
        source = where[:-len("objects.inv")]
        if not is_url:
            source = source.rstrip(os.sep) or os.sep
    else:
        source = where
    archive = None
    if kind == "sphinx" and fetch is not None:
        archive = find_source_archive(fetch, source)
    return Detection(kind, source, found, tried, archive)


def offline(d: Detection) -> bool:
    """True when nothing was found and no probe got a real answer."""
    return d.kind is None and bool(d.tried) and all(r == "network error" for _, r in d.tried)


def describe(d: Detection) -> List[str]:
    """The lines `detect` prints for a found type."""
    lines = ["type: %s" % d.kind, "source: %s" % d.source, "read: %s" % DOCS[d.kind]]
    if d.index:
        lines.append("index: %s" % d.index)
    for kind, where in d.found[1:]:
        lines.append("also: %s (%s)" % (kind, where))
    if d.archive:
        lines.append("archive: %s" % d.archive)
    return lines
