"""Find, download and safely unpack a Sphinx site's published HTML archive
(Read the Docs "htmlzip"). An archive is a delivery shortcut for the pages
of a site: every failure here means "no archive", and the caller falls back
to page-by-page fetching. Stdlib only.

Change check: the HTTP layer's opener is GET-only, so fetch_archive takes an
optional `head` callable (Source.head_url: a HEAD through the Source, so robots.txt is honoured). Without
it an existing archive is reused until --refetch; with it a different
Content-Length or Last-Modified from the stored ones triggers a download.
archive.json keeps url, size, last_modified and sha256.
"""
import hashlib
import json
import os
import posixpath
import shutil
import stat
import tarfile
import tempfile
import urllib.parse
import zipfile
import zlib
from typing import Callable, Dict, List, Optional, Tuple

from build_core import CLIError
from build_html import _SELECTORS, VOID, _element_end, _serialize, _tokens
from build_fetch import Source, _atomic_write, default_head  # noqa: F401 (re-export)

MAX_UNPACKED = 500 * 1024 * 1024
MAX_FILES = 50000
RTD_API = "https://readthedocs.org/api/v3/projects/%s/versions/%s/"

Getter = Callable[[str], Tuple[int, bytes]]
Header = Callable[[str], Tuple[int, Dict[str, str]]]


def _site_parts(site_url: str) -> Tuple[str, str, Optional[str], str, str]:
    """(origin, host, subproject slug or None, language, version)."""
    parts = urllib.parse.urlsplit(site_url)
    origin = "%s://%s" % (parts.scheme, parts.netloc)
    segs = [s for s in parts.path.split("/") if s]
    sub = None
    if len(segs) >= 2 and segs[0] == "projects":
        sub, segs = segs[1], segs[2:]
    lang = segs[0] if len(segs) >= 1 else "en"
    version = segs[1] if len(segs) >= 2 else "latest"
    return origin, parts.netloc.lower(), sub, lang, version


def find_archive(site_url: str, get: Getter, head: Optional[Header] = None) -> Optional[str]:
    """URL of the site's HTML archive, or None. Read the Docs API first (slug
    from <slug>.readthedocs.io or projects/<sub>/), then a probe of
    <origin>/_/downloads/<lang>/<version>/htmlzip/ (via `head` when given,
    else a GET). Any failure means None."""
    try:
        origin, host, sub, lang, version = _site_parts(site_url)
    except ValueError:
        return None
    slug = sub
    if slug is None and host.endswith(".readthedocs.io"):
        slug = host[: -len(".readthedocs.io")]
    if slug:
        try:
            status, body = get(RTD_API % (urllib.parse.quote(slug), urllib.parse.quote(version)))
            if status == 200:
                data = json.loads(body.decode("utf-8", "replace"))
                zipurl = (data.get("downloads") or {}).get("htmlzip") if isinstance(data, dict) else None
                if isinstance(zipurl, str) and urllib.parse.urlsplit(zipurl).scheme in ("http", "https"):
                    return zipurl
        except (ValueError, AttributeError, TypeError):
            pass
    if sub is not None:
        return None
    probe = "%s/_/downloads/%s/%s/htmlzip/" % (origin, lang, version)
    try:
        status = head(probe)[0] if head else get(probe)[0]
    except ValueError:
        return None
    return probe if status == 200 else None


def find_source_archive(source: Source, site_url: Optional[str] = None) -> Optional[str]:
    """find_archive for a URL Source (site_url defaults to its base), every
    request through the Source (robots.txt honoured); None for a local folder."""
    if not source.is_url:
        return None
    return find_archive(site_url or source.base, source.get_quiet, source.head_url)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_archive(url: str, dest_dir: str, source: Source, refetch: bool,
                  head: Optional[Header] = None) -> Tuple[str, bool]:
    """(archive path, downloaded now). Reuses an archive already in dest_dir
    unless refetch, or `head` reports a Content-Length or Last-Modified that
    differs from archive.json. Raises FetchError when the download fails."""
    meta_path = os.path.join(dest_dir, "archive.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}
    path = os.path.join(dest_dir, str(meta.get("file", "")))
    if (not refetch and meta.get("url") == url and meta.get("file")
            and os.path.isfile(path) and os.path.getsize(path) == meta.get("size")):
        changed = False
        if head:
            status, h = head(url)
            if status == 200:
                length = h.get("content-length")
                lm = h.get("last-modified")
                if length and length.isdigit() and int(length) != meta.get("size"):
                    changed = True
                if lm and meta.get("last_modified") and lm != meta.get("last_modified"):
                    changed = True
        if not changed:
            return path, False
    body = source.get_url(url)
    name = "archive.tar.gz" if body[:2] == b"\x1f\x8b" else "archive.zip"
    path = os.path.join(dest_dir, name)
    _atomic_write(path, body)
    last_modified = ""
    if head:
        status, h = head(url)
        if status == 200:
            last_modified = h.get("last-modified", "")
    meta = {"url": url, "file": name, "size": len(body),
            "last_modified": last_modified, "sha256": _sha256(body)}
    _atomic_write(meta_path, json.dumps(meta, indent=2).encode("utf-8"))
    return path, True


def _safe_parts(name: str) -> Optional[list]:
    """Path parts of a member name, or None when it is absolute or climbs."""
    n = name.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        return None
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None
    return parts


def _cap_error(what: str) -> CLIError:
    return CLIError("archive too large to unpack (%s)" % what, 2)


def _copy_capped(src, dest: str, total: int) -> int:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as out:
        while True:
            chunk = src.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UNPACKED:
                raise _cap_error("over %d MB unpacked" % (MAX_UNPACKED // (1024 * 1024)))
            out.write(chunk)
    return total


def _unzip(path: str, tmp: str) -> None:
    total = files = 0
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            raise _cap_error("over %d entries" % MAX_FILES)
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise _cap_error("over %d MB unpacked" % (MAX_UNPACKED // (1024 * 1024)))
        for info in infos:
            parts = _safe_parts(info.filename)
            if not parts:
                continue
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)  # 0 when the zip carries no file type
            if kind and kind not in (stat.S_IFREG, stat.S_IFDIR):
                continue
            dest = os.path.join(tmp, *parts)
            if info.filename.endswith("/") or kind == stat.S_IFDIR:
                os.makedirs(dest, exist_ok=True)
                continue
            files += 1
            if files > MAX_FILES:
                raise _cap_error("over %d files" % MAX_FILES)
            with z.open(info) as src:
                total = _copy_capped(src, dest, total)


def _untar(path: str, tmp: str) -> None:
    total = files = seen = 0
    with tarfile.open(path, "r:*") as t:
        for member in t:
            seen += 1
            if seen > MAX_FILES:
                raise _cap_error("over %d entries" % MAX_FILES)
            parts = _safe_parts(member.name)
            if not parts:
                continue
            dest = os.path.join(tmp, *parts)
            if member.isdir():
                os.makedirs(dest, exist_ok=True)
                continue
            if not member.isreg():
                continue
            files += 1
            if files > MAX_FILES:
                raise _cap_error("over %d files" % MAX_FILES)
            src = t.extractfile(member)
            if src is None:
                continue
            with src:
                total = _copy_capped(src, dest, total)


def find_build(root: str) -> Optional[str]:
    best = None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        if "objects.inv" in filenames:
            depth = os.path.relpath(dirpath, root).count(os.sep)
            if best is None or depth < best[0]:
                best = (depth, dirpath)
    if best:
        return best[1]
    if os.path.isfile(os.path.join(root, "index.html")):
        return root
    for name in sorted(os.listdir(root)):
        sub = os.path.join(root, name)
        if os.path.isfile(os.path.join(sub, "index.html")):
            return sub
    return None


def unpack(archive_path: str, out_dir: str) -> str:
    """Unpack a .zip or .tar.gz into out_dir, member by member: skips absolute
    names, '..' parts, links, devices; CLIError(.., 2) over MAX_UNPACKED bytes
    or MAX_FILES files, or when no build folder is found. out_dir exists only
    on success. Returns the build folder (objects.inv, else index.html)."""
    parent = os.path.dirname(os.path.abspath(out_dir))
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=parent, prefix=".unpack-")
    try:
        try:
            if zipfile.is_zipfile(archive_path):
                _unzip(archive_path, tmp)
            else:
                _untar(archive_path, tmp)
        except (zipfile.BadZipFile, tarfile.TarError, zlib.error, NotImplementedError,
                RuntimeError, EOFError, OSError) as e:
            raise CLIError("cannot unpack the archive: %s" % e, 2)
        build = find_build(tmp)
        if build is None:
            raise CLIError("no build (objects.inv or index.html) in the archive", 2)
        rel = os.path.relpath(build, tmp)
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        os.replace(tmp, out_dir)
        tmp = ""
        return out_dir if rel == "." else os.path.join(out_dir, rel)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


DOC_PREFIX = "document-"


def is_singlehtml(html: str) -> bool:
    """True when the page holds several documents (id="document-..." markers)."""
    return 'id="%s' % DOC_PREFIX in html or "id='%s" % DOC_PREFIX in html


def _balance(tokens: list) -> list:
    """Tokens with stray end tags dropped and open elements closed."""
    out, stack = [], []
    for tok in tokens:
        kind, t = tok[0], tok[1]
        if kind == "start" and t not in VOID:
            stack.append(t)
        elif kind == "end" and t not in VOID:
            if t not in stack:
                continue
            while stack[-1] != t:
                out.append(("end", stack.pop(), None))
            stack.pop()
        out.append(tok)
    out.extend(("end", t, None) for t in reversed(stack))
    return out


def split_singlehtml(html: str, docnames: List[str]) -> Dict[str, str]:
    """Split a Sphinx singlehtml page into one page per document.

    A docname is a page uri without '.html' ('guide/a.html' -> 'guide/a',
    'x/' -> 'x/index'; the page uri is docname + '.html'). Each document
    starts at the element with id="document-<docname>" (a '/' in the docname
    may appear as '-') and runs to the next such marker; 'index' gets the
    content before the first marker unless it has a marker of its own.
    Returns {docname: html} for the docnames found, each wrapped in
    <div role="main"> (what build_html.main_content picks), balanced, its
    own marker id removed. A link '#id' to an id defined in another chunk
    becomes '<uri of that page, relative to this one>#id'; '#document-x'
    becomes page x; ids in the same chunk stay. Linear time."""
    tokens = _tokens(html)
    inner = tokens
    for match in _SELECTORS:   # the same element main_content picks
        hit = next((i for i, (k, t, a) in enumerate(tokens)
                    if k == "start" and match(t, a or [])), None)
        if hit is not None:
            inner = tokens[hit + 1:_element_end(tokens, hit) - 1]
            break
    chunks: List[Tuple[str, list]] = [("index", [])]
    for tok in inner:
        if tok[0] == "start":
            ident = next((v for k, v in tok[2] or [] if k == "id"), None)
            if ident and ident.startswith(DOC_PREFIX):
                chunks.append((ident[len(DOC_PREFIX):], []))
        chunks[-1][1].append(tok)
    wanted: Dict[str, str] = {}
    for d in docnames:
        wanted[d] = d
        wanted.setdefault(d.replace("/", "-"), d)
    pages: Dict[str, list] = {}
    for name, raw in chunks:
        d = wanted.get(name, name)
        if d in pages or (d == "index" and not raw and name == "index"):
            continue
        toks = _balance(raw)
        if toks and toks[0][0] == "start":
            toks[0] = ("start", toks[0][1], [(k, v) for k, v in toks[0][2] or []
                                              if not (k == "id" and (v or "").startswith(DOC_PREFIX))])
        pages[d] = toks
    owner: Dict[str, str] = {}
    for d, toks in pages.items():
        for kind, _t, attrs in toks:
            if kind == "start":
                for k, v in attrs or []:
                    if k == "id" and v:
                        owner.setdefault(v, d)
    out: Dict[str, str] = {}
    for d, toks in pages.items():
        here = posixpath.dirname(d + ".html") or "."

        def href(value: str, d=d, here=here) -> str:
            path, _, ident = value.partition("#")
            if path not in ("", "index.html", "./index.html") or not ident:
                return value
            value = "#" + ident
            if ident.startswith(DOC_PREFIX):
                tgt = wanted.get(ident[len(DOC_PREFIX):], ident[len(DOC_PREFIX):])
                return posixpath.relpath(tgt + ".html", here) if tgt in pages else value
            tgt = owner.get(ident)
            if tgt is None or tgt == d:
                return value
            return posixpath.relpath(tgt + ".html", here) + value
        out[d] = '<div role="main">%s</div>' % _serialize(toks, href=href)
    return {d: out[d] for d in docnames if d in out}


def docname_of(uri: str) -> str:
    """'guide/a.html' -> 'guide/a'; 'x/' -> 'x/index'; '' -> 'index'."""
    uri = uri.split("#", 1)[0]
    if uri == "" or uri.endswith("/"):
        uri += "index"
    return uri[:-5] if uri.endswith(".html") else uri
