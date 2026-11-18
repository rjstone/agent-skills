"""docshelf core: errors and configuration (cache, notes, project file)."""
import json
import os
import re
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import unquote

VERSION = "0.8.1"
PROJECT_FILE = ".docshelf.json"


def warn(msg: str) -> None:
    print("warning: " + msg, file=sys.stderr)


STALE_TMP_SECONDS = 3600


def sweep_stale_tmp(folder: str, max_age: float = STALE_TMP_SECONDS) -> None:
    """Remove '*.tmp', '*.tmp-journal' and '*.tmp-wal' files in folder older
    than max_age seconds (leftovers of a killed run, SQLite's included);
    nothing else is touched. Errors are ignored.

    A live temp file is never old: whoever writes it keeps its mtime fresh,
    so the age test alone spares it. The owner's pid is not checked:
    os.kill(pid, 0) terminates the process on Windows."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    now = time.time()
    for n in names:
        if not n.endswith((".tmp", ".tmp-journal", ".tmp-wal")):
            continue
        p = os.path.join(folder, n)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > max_age:
                os.remove(p)
        except OSError:
            pass


def umask_mode() -> int:
    """The mode open() gives a new file: 0o666 minus the umask. Reading the
    umask means setting it and restoring it, which is safe here: docshelf is
    single-threaded."""
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


def make_temp(folder: str, prefix: str = "", sweep: bool = True):
    """tempfile.mkstemp(dir=folder, suffix='.tmp') with the permissions
    open() would give (0o666 minus the umask), not mkstemp's 0600. With
    sweep, old '*.tmp' files in folder are removed first. Returns (fd, path)."""
    if sweep:
        sweep_stale_tmp(folder)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=prefix, suffix=".tmp")
    try:
        mode = umask_mode()
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        else:
            os.chmod(tmp, mode)
    except OSError:
        pass
    return fd, tmp


class CLIError(Exception):
    """A user-facing error; main() prints the message and exits with code."""
    docvol: Optional[str] = None  # set when the error is an unknown docvol name

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


class UnusableDocvol(CLIError):
    """A docvol that cannot be used right now (default exit code 2, e.g. its
    cache copy cannot be written); multi-docvol commands skip it with a
    warning unless it was named with -d."""


class DamagedDocvol(UnusableDocvol):
    """A docvol whose files cannot be read (exit code 5)."""

    def __init__(self, message: str):
        super().__init__(message, 5)


def skip_damaged(docs: list, strict: bool, probe) -> list:
    """The docvols for which probe(d) does not raise UnusableDocvol. A damaged
    one is re-raised when strict (the user named docvols with -d), else
    warned about and dropped; the first error is raised when none is left."""
    kept, first = [], None
    for d in docs:
        try:
            probe(d)
        except UnusableDocvol as e:
            if strict:
                raise
            warn("skipping docvol %s: %s" % (d.name, e))
            first = first or e
            continue
        kept.append(d)
    if docs and not kept and first is not None:
        raise first
    return kept


class ScopeError(CLIError):
    """The request matches too much to print."""

    def __init__(self, message: str):
        super().__init__(message, 4)


@dataclass
class Config:
    cache_dir: str
    notes_dir: str
    project_file: Optional[str]
    project_docvols: List[str]
    cache_source: str  # "env" or "default"
    notes_source: str  # "env" or "default"
    project_note: Optional[str] = None  # set when a fallback found the file


def _home(env):
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise CLIError("cannot read %s: %s" % (path, e), 2)
    if not isinstance(data, dict):
        raise CLIError("%s: expected a JSON object" % path, 2)
    return data


def find_project_file(cwd):
    d = os.path.abspath(cwd)
    while True:
        candidate = os.path.join(d, PROJECT_FILE)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


USERS_FOLDERS = {"home", "users"}  # /home; /Users (macOS); \Users (Windows)


def walk_up(start, env) -> Iterator[str]:
    """start, its parent, and so on, for the fallback searches. The home
    folder is the last one checked; a folder that holds users' homes and a
    filesystem root never are."""
    home = os.path.normpath(_home(env))
    d = os.path.abspath(start)
    while True:
        parent = os.path.dirname(d)
        if parent == d or d == os.path.dirname(home):
            return
        if os.path.dirname(parent) == parent \
                and os.path.basename(d).lower() in USERS_FOLDERS:
            return
        yield d
        if d == home:
            return
        d = parent


def script_dir() -> str:
    """The script's folder as it was invoked (symlinks not resolved)."""
    return os.path.dirname(os.path.abspath(__file__))


def skill_dir() -> str:
    d = script_dir()
    return os.path.dirname(d) if os.path.basename(d) == "scripts" else d


def parent_process_dirs(limit=8) -> List[str]:
    """Working folders of this process's ancestors, nearest first (Linux
    /proc only; elsewhere an empty list). The shell that ran `cd X && python
    ...` is in X, but the program that started that shell usually is still
    in the project folder."""
    out, pid = [], os.getppid()
    for _ in range(limit):
        if pid <= 1:
            break
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if cwd not in out:
            out.append(cwd)
    return out


def fallback_bases(env) -> List[Tuple[str, str]]:
    """[(folder, what it is)] to search upward from when the current folder
    and its parents have no project file."""
    bases = [(script_dir(), "the script's folder")]
    if env.get("OLDPWD"):
        bases.append((env["OLDPWD"], "OLDPWD, the previous folder"))
    bases += [(d, "a parent process's folder") for d in parent_process_dirs()]
    seen, out = set(), []
    for d, what in bases:
        if os.path.isabs(d) and os.path.isdir(d) and d not in seen:
            seen.add(d)
            out.append((d, what))
    return out


def locate_project_file(cwd, env) -> Tuple[Optional[str], Optional[str]]:
    """(project file, None) from the current folder upward, else (file, what
    it was found from) from the fallback folders upward, else (None, None)."""
    path = find_project_file(cwd)
    if path:
        return path, None
    for base, what in fallback_bases(env):
        for d in walk_up(base, env):
            candidate = os.path.join(d, PROJECT_FILE)
            if os.path.isfile(candidate):
                return candidate, what
    return None, None


def _default_cache(env):
    if sys.platform == "win32" and env.get("LOCALAPPDATA"):
        return os.path.join(env["LOCALAPPDATA"], "docshelf", "cache")
    return os.path.join(_home(env), ".cache", "docshelf")


def _default_notes(env):
    if sys.platform == "win32" and env.get("APPDATA"):
        return os.path.join(env["APPDATA"], "docshelf", "notes")
    base = env.get("XDG_DATA_HOME") or os.path.join(_home(env), ".local", "share")
    return os.path.join(base, "docshelf", "notes")


def load_config(cwd: Optional[str] = None, env=None) -> Config:
    env = os.environ if env is None else env
    cwd = cwd or os.getcwd()
    cache, cache_src = env.get("DOCSHELF_CACHE_DIR"), "env"
    if not cache:
        cache, cache_src = _default_cache(env), "default"
    notes, notes_src = env.get("DOCSHELF_NOTES_DIR"), "env"
    if not notes:
        notes, notes_src = _default_notes(env), "default"
    project, found_from = locate_project_file(cwd, env)
    docvols: List[str] = []
    note = None
    if project:
        data = _load_json(project)
        value = data.get("docvols", [])
        if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
            raise CLIError('%s: "docvols" must be a list of strings' % project, 2)
        docvols = value
        if found_from:
            note = "using %s (found from %s; no %s in or above the " \
                "current folder)" % (project, found_from, PROJECT_FILE)
    return Config(os.path.normpath(cache), os.path.normpath(notes), project,
                  docvols, cache_src, notes_src, note)


# --- docvols ---------------------------------------------------------------

FULL_SIZE_MIN_ENTRIES = 500
MAX_FULL_UNSCOPED = 4


@dataclass(frozen=True)
class Entry:
    name: str
    type: str
    ref: str  # "<docvol name>:<backend part>"
    page: str
    anchor: Optional[str]


class Docvol(ABC):
    """One installed documentation set. Backends subclass it."""

    name: str
    family: str
    title: str
    release: str
    aliases: Tuple[str, ...] = ()
    entry_count: int = 0
    source: str = ""          # "devdocs", "dash", "zeal" or "folder"
    read_only: bool = False
    version: str = ""
    _href_known: Optional[set] = None

    @property
    def display_name(self) -> str:
        return self.__dict__.get("_display_name") or self.title

    @display_name.setter
    def display_name(self, value: str) -> None:
        self._display_name = value

    @property
    def full_size(self) -> bool:
        return self.entry_count >= FULL_SIZE_MIN_ENTRIES

    @abstractmethod
    def entries(self) -> List[Entry]:
        """Every entry, in index order."""

    @abstractmethod
    def pages(self) -> List[str]:
        """Page names."""

    @abstractmethod
    def page_html(self, page: str) -> str:
        """The page's HTML; CLIError(code 5) when there is no such page."""

    def page_blocks(self, page: str, link=None) -> "List[Block]":
        """The page as text blocks (see shelf_render.html_to_text)."""
        from shelf_render import html_to_text  # lazy: shelf_render imports us
        return html_to_text(self.page_html(page), link=link)

    def resolve_href(self, page: str, href: str) -> Optional[str]:
        """The REF a link on page points to, or None."""
        if self._href_known is None:
            self._href_known = set(self.pages())
        for decode in (True, False):  # a page name may hold a literal %XX
            target, frag = resolve_doc_path(page, href, decode)
            if target is not None and target in self._href_known:
                return self.make_ref(target, frag)
        return None

    @abstractmethod
    def resolve(self, rest: str) -> Tuple[str, Optional[str], Optional[Entry]]:
        """(page, anchor, the entry whose REF part is exactly rest or None)."""

    @abstractmethod
    def make_ref(self, page: str, anchor: Optional[str]) -> str:
        """The REF for a page and optional anchor."""

    @abstractmethod
    def stamp(self) -> str:
        """Changes whenever the docvol's content changes."""

    @abstractmethod
    def data_dir(self) -> str:
        """Folder for derived files."""


def resolve_doc_path(page, href, decode=True):
    """href resolved against the page's folder: '..' pops, a leading '/' is
    the docvol root; a '?query' is dropped and, with decode, each segment is
    percent-decoded (a decoded '/' splits it, so %2F and %2e%2e act like
    literal ones); returns (path, fragment or None). The fragment is
    returned as written. A '..' that climbs above the root gives path None."""
    rel, _, frag = href.partition("#")
    rel = rel.partition("?")[0]
    segments = [] if rel.startswith("/") else page.split("/")[:-1]
    for raw in rel.split("/"):
        for part in (unquote(raw).split("/") if decode else [raw]):
            if part in ("", "."):
                continue
            if part == "..":
                if not segments:
                    return None, frag or None
                segments.pop()
            else:
                segments.append(part)
    return "/".join(segments), frag or None


def rank(query: str, name: str) -> Optional[int]:
    """0 exact, 1 prefix, 2 substring, 3 fuzzy (in order), None no match."""
    q, n = query.lower(), name.lower()
    if n == q:
        return 0
    if n.startswith(q):
        return 1
    if q in n:
        return 2
    pos = 0
    for c in q:
        pos = n.find(c, pos) + 1
        if pos == 0:
            return None
    return 3


def pick_docvol(docvols, name, error=None) -> Docvol:
    """The docvol called name: exact name; else, case-insensitively, name,
    alias, family, then title. Several matches at one step are an error
    (code 2); no match is code 5 (or error(msg) when given)."""
    error = error or (lambda msg: CLIError(msg, 5))
    exact = next((d for d in docvols if d.name == name), None)
    if exact:
        return exact
    low = name.lower()
    steps = (
        ("name", lambda d: d.name.lower() == low),
        ("alias", lambda d: low in [a.lower() for a in d.aliases]),
        ("family", lambda d: d.family.lower() == low),
        ("title", lambda d: d.title.lower() == low),
    )
    for _, test in steps:
        found = [d for d in docvols if test(d)]
        if len(found) == 1:
            return found[0]
        if found:
            raise CLIError("%s matches %s; give one"
                           % (name, ", ".join(sorted(d.name for d in found))), 2)
    err = error("unknown docvol %r (see: docshelf.py list)" % name)
    err.docvol = name
    raise err


def select_docvols(cfg, all_docvols, names, use_all) -> List[Docvol]:
    """Scope: names > project list > all if <= 4 full-size or use_all.
    A name picks the docvol of that exact name, else every docvol of that
    family (a family name selects all its versions), else whatever
    pick_docvol finds (alias, title)."""
    wanted = names or cfg.project_docvols
    if wanted:
        chosen = []
        for n in wanted:
            low = n.lower()
            hit = ([d for d in all_docvols if d.name == n]
                   or [d for d in all_docvols if d.name.lower() == low]
                   or [d for d in all_docvols if d.family.lower() == low])
            if not hit:
                hit = [pick_docvol(all_docvols, n, ScopeError)]
            chosen.extend(hit)
        return [d for d in all_docvols if d in chosen]
    full = [d for d in all_docvols if d.full_size]
    if use_all or len(full) <= MAX_FULL_UNSCOPED:
        return list(all_docvols)
    counts: Dict[str, int] = {}
    for d in full:
        counts[d.family] = counts.get(d.family, 0) + 1
    listed = ", ".join("%s (%d)" % (f, c) if c > 1 else f
                       for f, c in sorted(counts.items()))
    raise ScopeError(
        "%d full-size docvols and no scope; searching all of them is slow and "
        "noisy.\nFull-size docvols: %s\nNarrow it with -d NAME (repeatable; "
        "a family name picks all its versions), a \"docvols\" list in %s, or "
        "search everything with --all."
        % (len(full), listed, PROJECT_FILE))


# Set by the MCP tool call while it runs: turns CLI wording in our own hint
# lines into tool wording. Never applied to text that came from the docs.
HINT_REWRITER: Optional[Callable[[str], str]] = None


def hint(text: str) -> str:
    """Our own hint text, in tool wording while an MCP call runs."""
    return HINT_REWRITER(text) if HINT_REWRITER else text


def same_family_note(docs) -> Optional[str]:
    """Note for the first family with two or more docvols in docs, or None."""
    groups: Dict[str, List[str]] = {}
    for d in docs:
        groups.setdefault(d.family, []).append(d.name)
    for family, names in groups.items():
        if len(names) > 1:
            return hint("note: searching %d docvols of %s (%s); -d NAME picks one"
                        % (len(names), family, ", ".join(names)))
    return None


def cap_lines(lines, max_lines, hint) -> List[str]:
    if len(lines) <= max_lines:
        return list(lines)
    cut = len(lines) - max_lines
    return list(lines[:max_lines]) + ["... %d more lines cut; %s" % (cut, hint)]


def short_name(name: str) -> str:
    """Entry name without an argument list: 'f(a, [b])' -> 'f' (lowercased)."""
    short = re.sub(r"\s*\(.*$", "", name).strip().lower()
    return short or name.lower()
