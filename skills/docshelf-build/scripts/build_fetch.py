"""Where a build reads from: a docs site URL or a local Sphinx HTML folder."""
import hashlib
import http.client
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

from build_core import VERSION, CLIError

USER_AGENT = "docshelf-build/" + VERSION
TIMEOUT = 30
RETRY_DELAYS = (1, 2, 4)        # seconds before retry 1, 2, 3
MAX_WORKERS = 4

Opener = Callable[[str], Tuple[int, bytes]]
HeadOpener = Callable[[str], Tuple[int, Dict[str, str]]]


class FetchError(Exception):
    def __init__(self, uri: str, reason: str):
        super().__init__("%s: %s" % (uri, reason))
        self.uri, self.reason = uri, reason


REDIRECTS = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5
TOO_MANY_REDIRECTS = 310  # pseudo status: not retried, see _status_text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand a redirect back to the caller as an HTTPError, so Source can
    re-check robots.txt for the host it points to before following it."""

    def redirect_request(self, *args, **kwargs):
        return None


_URL_OPENER = urllib.request.build_opener(_NoRedirect)


def default_opener(url: str) -> Tuple[int, bytes]:
    """GET url with docshelf-build's User-Agent: (HTTP status, body); status 0
    for a network failure. Only http and https. Redirects are not followed:
    a 301/302/303/307/308 answers (status, the Location value as bytes)."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("not an http(s) URL: %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # scheme checked above, so no file: or custom schemes
        with _URL_OPENER.open(req, timeout=TIMEOUT) as r:  # nosec B310
            return getattr(r, "status", 200), r.read()
    except urllib.error.HTTPError as e:
        if e.code in REDIRECTS:
            return e.code, (e.headers.get("Location") or "").encode("utf-8", "replace")
        return e.code, b""
    except http.client.InvalidURL as e:
        raise ValueError(str(e))
    except (urllib.error.URLError, OSError):
        return 0, b""


def default_head(url: str) -> Tuple[int, Dict[str, str]]:
    """HEAD url: (status, lower-cased headers); status 0 on a network failure.
    Redirects are not followed: the answer carries the `location` header."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("not an http(s) URL: %s" % url)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        # scheme checked above, so no file: or custom schemes
        with _URL_OPENER.open(req, timeout=TIMEOUT) as r:  # nosec B310
            return getattr(r, "status", 200), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        if e.code in REDIRECTS:
            return e.code, {"location": e.headers.get("Location") or ""}
        return e.code, {}
    except http.client.InvalidURL as e:
        raise ValueError(str(e))
    except (urllib.error.URLError, OSError):
        return 0, {}


def normalize_source(src: str) -> Tuple[str, bool]:
    """(base, is_url): a URL ending in "/" (a trailing page name such as
    index.html dropped), or an absolute folder path."""
    if src.startswith(("http://", "https://")):
        parts = urllib.parse.urlsplit(src)
        path = parts.path
        if not path.endswith("/"):
            last = path.rsplit("/", 1)[-1]
            path = path[: -len(last)] if last.endswith((".html", ".htm")) else path + "/"
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", "")), True
    path = os.path.realpath(src)
    if os.path.isfile(path) or path.endswith((".html", ".htm")):
        path = os.path.dirname(path)
    return path, False


class Source:
    def __init__(self, base: str, is_url: bool, live_base: Optional[str], opener: Opener,
                 workers: int, delay: float, sleep: Callable[[float], None]):
        self.base, self.is_url, self.live_base = base, is_url, live_base
        self.opener, self.workers, self.delay, self.sleep = opener, workers, delay, sleep
        self._robots: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()
        self.head_opener: Optional[HeadOpener] = None

    def live_url(self, uri: str) -> Optional[str]:
        return urllib.parse.urljoin(self.live_base, uri) if self.live_base else None

    def inventory(self) -> bytes:
        if self.is_url:
            url = self.base + "objects.inv"
            status, body = self._get(url)
            if status != 200:
                raise CLIError("cannot fetch %s: %s" % (url, _status_text(status)), 4)
            return body
        path = os.path.join(self.base, "objects.inv")
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            raise CLIError("no objects.inv in %s (%s)" % (self.base, e.strerror), 2)

    def file(self, rel: str) -> Optional[bytes]:
        """Bytes of an index file at `rel` under the base; None when it does
        not exist (404/410, or missing locally). FetchError when robots.txt
        blocks it, CLIError(4) for any other failed answer."""
        if self.is_url:
            url = urllib.parse.urljoin(self.base, rel)
            if not self._allowed(url):
                raise FetchError(url, "blocked by robots.txt")
            status, body = self._get(url)
            if status == 200:
                return body
            if status in (404, 410):
                return None
            raise CLIError("cannot fetch %s: %s" % (url, _status_text(status)), 4)
        path = os.path.realpath(os.path.join(self.base, *rel.split("/")))
        if os.path.commonpath([path, self.base]) != self.base:
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def page(self, uri: str) -> str:
        if self.is_url:
            url = urllib.parse.urljoin(self.base, uri)
            if not self._allowed(url):
                raise FetchError(uri, "blocked by robots.txt")
            status, body = self._get(url)
            if status != 200:
                raise FetchError(uri, _status_text(status))
            return body.decode("utf-8", "replace")
        rel = uri.split("#", 1)[0]
        if rel == "" or rel.endswith("/"):
            rel += "index.html"
        path = os.path.realpath(os.path.join(self.base, *rel.split("/")))
        if os.path.commonpath([path, self.base]) != self.base:
            raise FetchError(uri, "outside the source folder")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as e:
            raise FetchError(uri, "missing in the source folder (%s)" % e.strerror)

    def _follow(self, url: str, call: Callable, location: Callable, check: bool, empty):
        """call(url) -> (status, payload), following up to MAX_REDIRECTS
        redirects. Each target is checked against its own host's robots.txt
        when `check` (FetchError when blocked); a non-http(s) target, or too
        many hops, ends in a status that is not retried."""
        for _ in range(MAX_REDIRECTS + 1):
            status, payload = call(url)
            if status not in REDIRECTS:
                return status, payload
            loc = location(payload)
            if not loc:
                return status, payload
            url = urllib.parse.urljoin(url, loc)
            if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                return 400, empty
            if check and not self._allowed(url):
                raise FetchError(url, "blocked by robots.txt")
        return TOO_MANY_REDIRECTS, empty

    def _open(self, url: str, check: bool = True) -> Tuple[int, bytes]:
        """One GET, redirects followed (see _follow); a malformed URL
        (ValueError, UnicodeError from idna, http.client.InvalidURL) is a
        FetchError that is not retried."""
        try:
            return self._follow(url, self.opener, lambda b: b.decode("utf-8", "replace").strip(),
                                check, b"")
        except (ValueError, UnicodeError, http.client.InvalidURL):
            raise FetchError(url, "invalid URL")

    def _get(self, url: str) -> Tuple[int, bytes]:
        """GET with retries on 429, 5xx and network failures."""
        status, body = self._open(url)
        for wait in RETRY_DELAYS:
            if not (status == 0 or status == 429 or status >= 500):
                break
            self.sleep(wait)
            status, body = self._open(url)
        return status, body

    def get_url(self, url: str) -> bytes:
        """Body of an absolute URL after the robots.txt check; FetchError on
        a block or any non-200 answer."""
        try:
            allowed = self._allowed(url)
        except ValueError:
            raise FetchError(url, "invalid URL")
        if not allowed:
            raise FetchError(url, "blocked by robots.txt")
        status, body = self._get(url)
        if status != 200:
            raise FetchError(url, _status_text(status))
        return body

    def get_quiet(self, url: str) -> Tuple[int, bytes]:
        """(status, body) of a GET after the robots.txt check; (0, b"") when
        robots.txt blocks it, the URL is invalid or the request fails. Never
        raises."""
        try:
            if not self._allowed(url):
                return 0, b""
            return self._get(url)
        except (ValueError, FetchError):
            return 0, b""

    def head_url(self, url: str) -> Tuple[int, Dict[str, str]]:
        """(status, lower-cased headers) of a HEAD after the robots.txt check;
        (0, {}) when robots.txt blocks it, the URL is invalid, or this Source
        has no HEAD opener (a GET-only fake opener)."""
        if self.head_opener is None:
            return 0, {}
        try:
            if not self._allowed(url):
                return 0, {}
            return self._follow(url, self.head_opener, lambda h: (h.get("location") or "").strip(),
                                True, {})
        except (ValueError, FetchError):
            return 0, {}

    def _allowed(self, url: str) -> bool:
        """robots.txt of the URL's own host, fetched once per scheme://netloc
        (for a Sphinx source that is the host of base)."""
        parts = urllib.parse.urlsplit(url if url else self.base)
        origin = "%s://%s" % (parts.scheme, parts.netloc)
        with self._lock:
            rp = self._robots.get(origin)
            if rp is None:
                status, body = self._open(origin + "/robots.txt", check=False)
                rp = urllib.robotparser.RobotFileParser()
                if status in (401, 403):
                    rp.disallow_all = True
                elif status == 200:
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                else:
                    rp.allow_all = True
                self._robots[origin] = rp
        return rp.can_fetch(USER_AGENT, url)


def _status_text(status: int) -> str:
    if status == TOO_MANY_REDIRECTS:
        return "too many redirects"
    return "network error" if status == 0 else "HTTP %d" % status


def open_source(src: str, base_url: Optional[str] = None, workers: int = 1,
                delay: float = 0.5, opener: Optional[Opener] = None,
                sleep: Optional[Callable[[float], None]] = None,
                head_opener: Optional[HeadOpener] = None) -> Source:
    base, is_url = normalize_source(src)
    live = base if is_url else (normalize_source(base_url)[0] if base_url else None)
    s = Source(base, is_url, live, opener or default_opener,
               max(1, min(workers, MAX_WORKERS)), delay, sleep or time.sleep)
    s.head_opener = head_opener or (default_head if opener is None else None)
    return s


def fetch_pages(source: Source, uris: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(html by uri, failure reason by uri). A failed page is reported, not
    raised; requests are paced by source.delay per worker."""
    html: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    def one(uri: str) -> None:
        try:
            html[uri] = source.page(uri)
        except FetchError as e:
            errors[uri] = e.reason
        if source.is_url and source.delay:
            source.sleep(source.delay)

    if source.workers == 1:
        for u in uris:
            one(u)
    else:
        with ThreadPoolExecutor(max_workers=source.workers) as pool:
            list(pool.map(one, uris))
    return html, errors


def open_url_source(workers: int = 1, delay: float = 0.5, opener: Optional[Opener] = None,
                    sleep: Optional[Callable[[float], None]] = None,
                    head_opener: Optional[HeadOpener] = None) -> Source:
    """A Source for fetching absolute URLs (llms.txt builds): no base."""
    s = Source("", True, None, opener or default_opener,
               max(1, min(workers, MAX_WORKERS)), delay, sleep or time.sleep)
    s.head_opener = head_opener or (default_head if opener is None else None)
    return s


def index_getter(source: Source) -> Callable[[str], str]:
    """get_text for build_llms.read_tree: a URL's text, CLIError on failure."""
    def get(url: str) -> str:
        try:
            return source.get_url(url).decode("utf-8", "replace")
        except FetchError as e:
            raise CLIError("cannot fetch %s: %s" % (url, e.reason), 4)
    return get


def looks_html(body: str) -> bool:
    """True when the text starts (after whitespace) like an HTML document."""
    head = body.lstrip("\ufeff").lstrip()[:15].lower()
    return head.startswith(("<!doctype", "<html"))


def fetch_llms_page(source: Source, url: str) -> Tuple[str, str]:
    """(text, "md"|"html") for a listed page. An HTML answer is retried once
    at the URL path + ".md", query kept, fragment dropped (unless url already ends .md/.mdx); the HTML is kept when
    the retry fails or is HTML too."""
    text = source.get_url(url).decode("utf-8", "replace")
    if not looks_html(text):
        return text, "md"
    if urllib.parse.urlsplit(url).path.lower().endswith((".md", ".mdx")):
        return text, "html"
    try:
        parts = urllib.parse.urlsplit(url)
        alt_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path.rstrip("/") + ".md", parts.query, ""))
        alt = source.get_url(alt_url).decode("utf-8", "replace")
    except FetchError:
        return text, "html"
    return (text, "html") if looks_html(alt) else (alt, "md")


def _iso(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class PageCache:
    """Fetched llms pages on disk: root/<key>.<type> plus manifest.json
    {key: {url, sha256, fetched, type}}, every file written atomically."""

    def __init__(self, root: str):
        self.root = root
        self._lock = threading.Lock()
        self._pending: Optional[dict] = None   # manifest updated this run, unwritten

    def _path(self, key: str, kind: str) -> str:
        real_root = os.path.realpath(self.root)
        path = os.path.realpath(os.path.join(real_root, *key.split("/")) + "." + kind)
        if os.path.commonpath([path, real_root]) != real_root:
            raise ValueError("page key outside the cache: %r" % key)
        return path

    def manifest(self) -> dict:
        if self._pending is not None:
            return dict(self._pending)
        return self._read_manifest()

    def _read_manifest(self) -> dict:
        try:
            with open(os.path.join(self.root, "manifest.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> Optional[Tuple[str, str]]:
        entry = self.manifest().get(key)
        if not isinstance(entry, dict) or entry.get("type") not in ("md", "html"):
            return None
        try:
            with open(self._path(key, entry["type"]), encoding="utf-8") as fh:
                return fh.read(), entry["type"]
        except (OSError, ValueError):
            return None

    def put(self, key: str, url: str, text: str, kind: str, now: float) -> None:
        path = self._path(key, kind)
        data = text.encode("utf-8")
        with self._lock:
            _atomic_write(path, data)
            if self._pending is None:
                self._pending = self._read_manifest()
            manifest = self._pending
            old = manifest.get(key)
            if isinstance(old, dict) and old.get("type") in ("md", "html") and old["type"] != kind:
                try:
                    os.remove(self._path(key, old["type"]))
                except (OSError, ValueError):
                    pass
            manifest[key] = {"url": url, "sha256": hashlib.sha256(data).hexdigest(),
                             "fetched": _iso(now), "type": kind}

    def flush(self) -> None:
        """Write the manifest atomically (once per run, not per page)."""
        with self._lock:
            if self._pending is None:
                return
            _atomic_write(os.path.join(self.root, "manifest.json"),
                          json.dumps(self._pending, indent=1, sort_keys=True).encode("utf-8"))
            self._pending = None


def fetch_llms(source: Source, pages: List[Tuple[str, str]], cache: PageCache,
               refetch: bool, now: float) -> Tuple[Dict[str, Tuple[str, str]],
                                                   Dict[str, str], Dict[str, str]]:
    """(raw by key, error by key, fetched ISO time by key) for (key, url)
    pages. Cached pages are reused unless refetch; a failed page falls back to
    its cached copy (still listed in errors). Paced like fetch_pages."""
    raw: Dict[str, Tuple[str, str]] = {}
    errors: Dict[str, str] = {}
    fetched: Dict[str, str] = {}

    def one(item: Tuple[str, str]) -> None:
        key, url = item
        if not refetch:
            hit = cache.get(key)
            if hit is not None:
                raw[key] = hit
                return
        try:
            text, kind = fetch_llms_page(source, url)
            cache.put(key, url, text, kind, now)
            raw[key] = (text, kind)
            fetched[key] = _iso(now)
        except FetchError as e:
            errors[key] = e.reason
            hit = cache.get(key)
            if hit is not None:
                raw[key] = hit
        except (ValueError, OSError) as e:
            errors[key] = "cannot store page: %s" % (getattr(e, "strerror", None) or e)
            hit = cache.get(key)
            if hit is not None:
                raw[key] = hit
        if source.delay:
            source.sleep(source.delay)

    try:
        if source.workers == 1:
            for item in pages:
                one(item)
        else:
            with ThreadPoolExecutor(max_workers=source.workers) as pool:
                list(pool.map(one, pages))
    finally:
        cache.flush()
    return raw, errors, fetched
