"""docshelf core: errors and configuration (cache, notes, project file)."""
import json
import os
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

VERSION = "0.2.0"
PROJECT_FILE = ".docshelf.json"


class CLIError(Exception):
    """A user-facing error; main() prints the message and exits with code."""
    docvol: Optional[str] = None  # set when the error is an unknown docvol name

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


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
    """Scope: names > project list > all if <= 4 full-size or use_all."""
    wanted = names or cfg.project_docvols
    if wanted:
        picked = []
        for n in wanted:
            d = pick_docvol(all_docvols, n, ScopeError)
            if d not in picked:
                picked.append(d)
        return picked
    full = [d for d in all_docvols if d.full_size]
    if use_all or len(full) <= MAX_FULL_UNSCOPED:
        return list(all_docvols)
    raise ScopeError(
        "%d full-size docvols and no scope; searching all of them is slow and "
        "noisy.\nFull-size docvols: %s\nNarrow it with -d NAME (repeatable), "
        "a \"docvols\" list in %s, or search everything with --all."
        % (len(full), ", ".join(d.name for d in full), PROJECT_FILE))


def cap_lines(lines, max_lines, hint) -> List[str]:
    if len(lines) <= max_lines:
        return list(lines)
    cut = len(lines) - max_lines
    return list(lines[:max_lines]) + ["... %d more lines cut; %s" % (cut, hint)]


def short_name(name: str) -> str:
    """Entry name without an argument list: 'f(a, [b])' -> 'f' (lowercased)."""
    short = re.sub(r"\s*\(.*$", "", name).strip().lower()
    return short or name.lower()
