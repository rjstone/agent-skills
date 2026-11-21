"""Where a build reads from: a docs site URL or a local Sphinx HTML folder."""
import os
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


class FetchError(Exception):
    def __init__(self, uri: str, reason: str):
        super().__init__("%s: %s" % (uri, reason))
        self.uri, self.reason = uri, reason


def default_opener(url: str) -> Tuple[int, bytes]:
    """GET url with docshelf-build's User-Agent: (HTTP status, body); status 0
    for a network failure. Only http and https."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("not an http(s) URL: %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # scheme checked above, so no file: or custom schemes
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # nosec B310
            return getattr(r, "status", 200), r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


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
        self._robots = None

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

    def _get(self, url: str) -> Tuple[int, bytes]:
        """GET with retries on 429, 5xx and network failures."""
        status, body = self.opener(url)
        for wait in RETRY_DELAYS:
            if not (status == 0 or status == 429 or status >= 500):
                break
            self.sleep(wait)
            status, body = self.opener(url)
        return status, body

    def _allowed(self, url: str) -> bool:
        if self._robots is None:
            parts = urllib.parse.urlsplit(self.base)
            robots_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/robots.txt",
                                                  "", ""))
            status, body = self.opener(robots_url)
            rp = urllib.robotparser.RobotFileParser()
            if status in (401, 403):
                rp.disallow_all = True
            elif status == 200:
                rp.parse(body.decode("utf-8", "replace").splitlines())
            else:
                rp.allow_all = True
            self._robots = rp
        return self._robots.can_fetch(USER_AGENT, url)


def _status_text(status: int) -> str:
    return "network error" if status == 0 else "HTTP %d" % status


def open_source(src: str, base_url: Optional[str] = None, workers: int = 1,
                delay: float = 0.5, opener: Optional[Opener] = None,
                sleep: Optional[Callable[[float], None]] = None) -> Source:
    base, is_url = normalize_source(src)
    live = base if is_url else (normalize_source(base_url)[0] if base_url else None)
    return Source(base, is_url, live, opener or default_opener,
                  max(1, min(workers, MAX_WORKERS)), delay, sleep or time.sleep)


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
