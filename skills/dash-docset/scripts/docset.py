#!/usr/bin/env python3
"""Install Dash docsets and search them offline (stdlib only)."""
import argparse
import json
import os
import sys
import pathlib
import re
import shutil
import sqlite3
import http.client
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit
from dataclasses import dataclass, field
from typing import Iterator, List, Mapping, Optional, Tuple

# Script version. Bump it (and SKILL.md's metadata.version to at least the
# same value) only when this script changes; SKILL.md may run ahead of it.
VERSION = "0.1.0"

PROJECT_FILE = ".dash-docset.json"
GITIGNORE_LINES = ["*", "!.gitignore", "!notes/", "!notes/**"]

SUBCOMMANDS = {
    "where": "show the docset store location",
    "sources": "list docset sources",
    "install": "install a docset",
    "update": "update installed docsets",
    "list": "list installed docsets",
    "remove": "remove an installed docset",
    "search": "search a docset's index",
    "show": "show a documentation page",
    "fts": "full-text search a docset",
    "index-text": "build the full-text index",
    "notes": "print a docset's notes, their path (to edit) or a size check",
}


class CLIError(Exception):
    """An error that main() prints to stderr and turns into exit code `code`."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


@dataclass
class Store:
    path: str
    source: str
    read_from: List[str]
    project_docsets: Optional[List[str]]


def _home(env):
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def _abs(path, base, env):
    """Absolute, normalised path; ~ expands from env; relative resolves against base."""
    if path == "~" or path.startswith(("~/", "~\\")):
        path = os.path.join(_home(env), path[2:])
    return os.path.normpath(os.path.join(base, path))


def user_config_path(env):
    if sys.platform == "win32" and env.get("APPDATA"):
        base = env["APPDATA"]
    else:
        base = env.get("XDG_CONFIG_HOME") or os.path.join(_home(env), ".config")
    return os.path.join(base, "dash-docset", "config.json")


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


def _try_load(path):
    """(data, None) or ({}, CLIError) so a bad config only matters if it is used."""
    try:
        return _load_json(path), None
    except CLIError as e:
        return {}, e


def resolve_store(cli_dir, cwd, env) -> Optional[Store]:
    """--dir > DASH_DOCSET_DIR > project file > user config > None.

    A malformed config is an error only when it is the one that decides; for
    --dir/DASH_DOCSET_DIR it is ignored (read_from then comes from the project
    config, else the user config, whichever parses)."""
    project_path = find_project_file(cwd)
    project, project_err = _try_load(project_path) if project_path else ({}, None)
    project_base = os.path.dirname(project_path) if project_path else cwd
    docsets = project.get("docsets") if project_path else None
    user_path = user_config_path(env)
    user, user_err = (_try_load(user_path) if os.path.isfile(user_path)
                      else ({}, None))
    user_base = os.path.dirname(user_path)

    def read_from(cfg, base):
        return [_abs(p, base, env) for p in cfg.get("read_from", [])]

    explicit = cli_dir or env.get("DASH_DOCSET_DIR")
    if explicit:
        if "read_from" in project:
            ro = read_from(project, project_base)
        else:
            ro = read_from(user, user_base)
        if cli_dir:
            return Store(_abs(cli_dir, cwd, env), "--dir", ro, docsets)
        return Store(_abs(env["DASH_DOCSET_DIR"], cwd, env), "DASH_DOCSET_DIR",
                     ro, docsets)
    if project_err:
        raise project_err
    if project.get("store"):
        return Store(_abs(project["store"], project_base, env), "project file",
                     read_from(project, project_base), docsets)
    if user_err:
        raise user_err
    if user.get("store"):
        return Store(_abs(user["store"], user_base, env),
                     "user config", read_from(user, user_base), docsets)
    return None


def discover(env) -> List[str]:
    """Existing docset folders of dasht, Zeal and Dash (read-only hints)."""
    home = _home(env)
    data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    candidates = [
        env.get("DASHT_DOCSETS_DIR"),
        os.path.join(data, "dasht", "docsets"),
        os.path.join(home, ".local", "share", "Zeal", "Zeal", "docsets"),
        os.path.join(env["LOCALAPPDATA"], "Zeal", "Zeal", "docsets")
        if env.get("LOCALAPPDATA") else None,
        os.path.join(home, "Library", "Application Support", "Dash", "DocSets"),
    ]
    found = []
    for c in candidates:
        if c and os.path.isdir(c) and c not in found:
            found.append(c)
    return found


def require_store(args, cwd=None, env=None) -> Store:
    """The resolved store, or CLIError(code 3) listing discovered folders."""
    env = os.environ if env is None else env
    store = resolve_store(getattr(args, "dir", None), cwd or os.getcwd(), env)
    if store is None:
        lines = ["storage location not set",
                 "Set one with: docset.py where --set PATH (--project | --user),",
                 "or --dir PATH, or DASH_DOCSET_DIR."]
        found = discover(env)
        if found:
            lines.append("Existing docset folders found (other tools; read-only "
                         "candidates for --read-from):")
            lines += ["  " + f for f in found]
        raise CLIError("\n".join(lines), 3)
    return store


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def cmd_where(args):
    env, cwd = os.environ, os.getcwd()
    if args.set:
        if args.project == args.user:
            raise CLIError("where --set needs exactly one of --project or --user", 2)
        if args.project:
            target = os.path.join(cwd, PROJECT_FILE)
            base = cwd
        else:
            target = user_config_path(env)
            base = os.path.dirname(target)
        data = _load_json(target) if os.path.isfile(target) else {}
        data["store"] = args.set
        if args.read_from:
            data["read_from"] = list(args.read_from)
        _write_json(target, data)
        store_dir = _abs(args.set, base, env)
        os.makedirs(store_dir, exist_ok=True)
        if (args.project and os.path.basename(store_dir) == ".docsets"
                and os.path.dirname(store_dir) == os.path.normpath(cwd)):
            gi = os.path.join(store_dir, ".gitignore")
            if not os.path.exists(gi):
                with open(gi, "w", encoding="utf-8") as f:
                    f.write("\n".join(GITIGNORE_LINES) + "\n")
        print("wrote %s (store: %s)" % (target, store_dir))
        return 0
    if args.discover:
        found = discover(env)
        print("\n".join(found) if found else "no existing docset folders found")
        return 0
    store = resolve_store(args.dir, cwd, env)
    if store is None:
        print("storage location not set (use where --set PATH --project|--user)")
        return 3
    print("store: %s" % store.path)
    print("source: %s" % store.source)
    for r in store.read_from:
        print("read-from: %s" % r)
    if store.project_docsets is not None:
        print("project docsets: %s" % ", ".join(store.project_docsets))
    return 0


FULL_SIZE_MIN_ENTRIES = 500


@dataclass
class Docset:
    name: str
    path: str
    foreign: bool
    source: Optional[str]
    version: Optional[str]
    entry_count: int
    clashes: List[str] = field(default_factory=list)  # shadowed foreign copies

    @property
    def full_size(self) -> bool:
        if self.source == "cheat":
            return False
        if (self.foreign or self.source is None) and self.entry_count < FULL_SIZE_MIN_ENTRIES:
            return False
        return True


def meta_dir(store) -> str:
    return os.path.join(store.path, ".dash-docset")


def load_installed(store) -> dict:
    path = os.path.join(meta_dir(store), "installed.json")
    if not os.path.isfile(path):
        return {}
    return _load_json(path)


def save_installed(store, data) -> None:
    d = meta_dir(store)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="installed.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, os.path.join(d, "installed.json"))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def index_path(docset_path) -> str:
    return os.path.join(docset_path, "Contents", "Resources", "docSet.dsidx")


def _open_ro(path):
    uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def count_entries(docset_path) -> int:
    con = _open_ro(index_path(docset_path))
    try:
        tables = _tables(con)
        table = "searchIndex" if "searchIndex" in tables else (
            "ZTOKEN" if "ZTOKEN" in tables else None)
        if table is None:
            raise ValueError("no searchIndex or ZTOKEN table")
        return con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        con.close()


def like_pattern(query) -> str:
    """dasht's fuzzy pattern %a%b%c% with %, _ and \\ escaped (ESCAPE '\\')."""
    esc = ["\\" + c if c in "%_\\" else c for c in query]
    return "%" + "%".join(esc) + "%"


def iter_entries(ds, like: Optional[str] = None,
                 entry_id: Optional[int] = None) -> Iterator[Tuple[int, str, str, str]]:
    """Yield (id, name, type, path) from either index form.

    like: optional SQL LIKE pattern (ESCAPE '\\') the name must match.
    entry_id: optional id; only that entry is read (a keyed lookup)."""
    con = _open_ro(index_path(ds.path))
    try:
        has_search_index = "searchIndex" in _tables(con)
        if has_search_index:
            sql = "SELECT id, name, type, path FROM searchIndex"
            id_col, name_col = "id", "name"
        else:
            sql = ("SELECT k.Z_PK, k.ZTOKENNAME, ty.ZTYPENAME, f.ZPATH, m.ZANCHOR "
                   "FROM ZTOKEN k "
                   "LEFT JOIN ZTOKENTYPE ty ON ty.Z_PK = k.ZTOKENTYPE "
                   "LEFT JOIN ZTOKENMETAINFORMATION m ON m.Z_PK = k.ZMETAINFORMATION "
                   "LEFT JOIN ZFILEPATH f ON f.Z_PK = m.ZFILE")
            id_col, name_col = "k.Z_PK", "k.ZTOKENNAME"
        where, params = [], []
        if like is not None:
            where.append("%s LIKE ? ESCAPE '\\'" % name_col)
            params.append(like)
        if entry_id is not None:
            where.append("%s = ?" % id_col)
            params.append(entry_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY " + id_col
        if has_search_index:
            for i, n, t, p in con.execute(sql, params):
                yield i, n, t or "", p or ""
        else:
            for i, n, t, p, a in con.execute(sql, params):
                yield i, n, t or "", (p or "") + ("#" + a if a else "")
    finally:
        con.close()


def _docset_dirs(root, depth):
    """*.docset folders directly in root (and one level down when depth=2)."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return
    for n in names:
        full = os.path.join(root, n)
        if n.endswith(".docset"):
            if os.path.isdir(full):
                yield full
        elif depth > 1 and os.path.isdir(full):
            for sub in _docset_dirs(full, depth - 1):
                yield sub


def _warn(msg):
    print("warning: " + msg, file=sys.stderr)


def _make_docset(path, foreign, source, version):
    name = os.path.basename(path)[:-len(".docset")]
    try:
        count = count_entries(path)
    except (sqlite3.Error, OSError, ValueError) as e:
        _warn("skipping unreadable docset %s: %s" % (path, e))
        return None
    return Docset(name, path, foreign, source, version, count)


def find_docsets(store) -> List[Docset]:
    """Docsets of the store (flat), then of each read_from dir (foreign)."""
    installed = load_installed(store)
    result = {}
    for path in _docset_dirs(store.path, 1):
        name = os.path.basename(path)[:-len(".docset")]
        meta = installed.get(name)
        meta = meta if isinstance(meta, dict) else {}
        ds = _make_docset(path, False, meta.get("source"), meta.get("version"))
        if ds:
            result[ds.name] = ds
    for root in store.read_from:
        for path in _docset_dirs(root, 2):
            ds = _make_docset(path, True, None, None)
            if ds is None:
                continue
            if ds.name in result:
                if result[ds.name].foreign:
                    continue  # first read_from copy wins
                result[ds.name].clashes.append(os.path.dirname(path))
                continue
            result[ds.name] = ds
    return list(result.values())


class ScopeError(CLIError):
    def __init__(self, message):
        super().__init__(message, 4)


MAX_FULL_UNSCOPED = 4


def parse_ref(ref: str) -> Tuple[str, int]:
    """'<DocsetName>:<id>' -> (name, id); the id follows the last colon."""
    name, sep, num = ref.rpartition(":")
    if not sep or not name or not (num.isascii() and num.isdecimal()):
        raise CLIError("bad reference %r (expected <Docset>:<id>)" % ref, 2)
    return name, int(num)


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


def select_docsets(store, all_docsets, names, use_all) -> List[Docset]:
    """Scope: -d names > project list > all if <= 4 full-size or use_all."""
    by_name = {d.name: d for d in all_docsets}
    wanted = names or store.project_docsets
    if wanted:
        picked = []
        for n in wanted:
            if n not in by_name:
                raise ScopeError("unknown docset %r (see: docset.py list)" % n)
            if by_name[n] not in picked:
                picked.append(by_name[n])
        return picked
    full = [d for d in all_docsets if d.full_size]
    if use_all or len(full) <= MAX_FULL_UNSCOPED:
        return list(all_docsets)
    raise ScopeError(
        "%d full-size docsets and no scope; searching all of them is slow and "
        "noisy.\nFull-size docsets: %s\nNarrow it with -d NAME (repeatable), "
        "a \"docsets\" list in %s, or search everything with --all."
        % (len(full), ", ".join(d.name for d in full), PROJECT_FILE))


def cap_lines(lines, max_lines, hint) -> List[str]:
    if len(lines) <= max_lines:
        return list(lines)
    cut = len(lines) - max_lines
    return list(lines[:max_lines]) + ["... %d more lines cut; %s" % (cut, hint)]


def cmd_search(args):
    if not args.query:
        raise CLIError("empty search query", 2)
    store = require_store(args)
    docs = select_docsets(store, find_docsets(store), args.docset or [], args.all)
    like = like_pattern(args.query)
    want_type = args.type.lower() if args.type else None
    hits = []
    for ds in docs:
        try:
            for i, name, typ, _path in iter_entries(ds, like):
                if want_type is not None and typ.lower() != want_type:
                    continue
                r = rank(args.query, name)
                if r is not None:
                    hits.append((r, len(name), name, ds.name, i, typ))
        except sqlite3.Error as e:
            _warn("skipping %s: %s" % (ds.name, e))
    hits.sort(key=lambda h: h[:4] + (h[4],))
    hint = "raise --max-lines or narrow the query, -d or --type"
    if args.json:
        items = [{"ref": "%s:%d" % (d, i), "docset": d, "type": t, "name": n,
                  "rank": r} for r, _l, n, d, i, t in hits[:args.max_lines]]
        print(json.dumps(items, indent=2))
        return 0
    lines = []
    for k, (r, _l, n, d, i, t) in enumerate(hits):
        if r == 3 and (k == 0 or hits[k - 1][0] < 3):
            lines.append("no exact, prefix or substring matches; fuzzy matches "
                         "(letters in order, often unrelated):" if k == 0 else
                         "--- fuzzy matches (letters in order, often unrelated) ---")
        lines.append("%s:%d  %s  %s  (%s)" % (d, i, t, n, d))
    if not hits:
        lines.append("no matches for %r" % args.query)
    for line in cap_lines(lines, args.max_lines, hint):
        print(line)
    return 0


@dataclass
class Block:
    level: int        # heading level 1-6, 0 for other blocks
    ids: List[str]    # ids / <a name> seen since the last emitted block
    text: str         # one or more lines
    tag: str          # element that started the block (the id carrier if any)
    depth: int        # open dl/table/ul/ol containers


SKIP_TAGS = {"script", "style", "nav", "header", "footer", "form", "select",
             "noscript", "template"}
SKIP_ROLES = {"navigation", "search", "banner", "contentinfo"}
# Navigation chrome of common doc generators (Sphinx, Read the Docs, ...);
# "headerlink" is the pilcrow link after Sphinx headings.
SKIP_CLASSES = {"related", "mobile-nav", "sphinxsidebar", "sphinxsidebarwrapper",
                "breadcrumbs", "breadcrumb", "wy-nav-side", "rst-versions",
                "headerlink", "toc-drawer", "sidebar-drawer", "skip-link"}


def _skippable(tag, a) -> bool:
    return (tag in SKIP_TAGS or a.get("role") in SKIP_ROLES
            or bool(SKIP_CLASSES.intersection((a.get("class") or "").split())))
CONTAINER_TAGS = {"dl", "table", "ul", "ol"}
BLOCK_TAGS = {"p", "div", "li", "dt", "dd", "tr", "pre", "ul", "ol", "dl", "table",
              "section", "article", "blockquote", "caption", "details", "summary",
              "figure", "figcaption", "body", "main", "aside", "address", "form",
              "fieldset", "hr", "h1", "h2", "h3", "h4", "h5", "h6"}
HEADINGS = {"h%d" % i: i for i in range(1, 7)}
CLOSES_SAME = {"li": ("li",), "dt": ("dt", "dd"), "dd": ("dt", "dd"), "p": ("p",),
               "tr": ("tr",)}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[Block] = []
        self.buf: List[str] = []
        self.stack: List[str] = []
        self.skip = 0
        self.in_pre = False
        self.depth = 0
        self.level = 0
        self.prefix = ""
        self.ids: List[str] = []
        self.id_tag = ""
        self.start_depth = 0
        self.skip_tag = ""

    def _top(self):
        return self.stack[-1] if self.stack else ""

    def flush(self):
        raw = "".join(self.buf)
        self.buf = []
        if self.in_pre:
            text = raw.strip("\n").rstrip()
            text = "```\n" + text + "\n```" if text.strip() else ""
        else:
            text = " ".join(raw.split())
        if not text:
            self.level = 0
            if self.prefix != "- ":
                self.prefix = ""
            return
        if self.level:
            tag = "h%d" % self.level
            text = "#" * self.level + " " + text
        else:
            tag = self.id_tag or self._top()
            text = self.prefix + text
        self.blocks.append(Block(self.level, self.ids, text, tag, self.start_depth))
        self.ids, self.id_tag, self.level, self.prefix = [], "", 0, ""

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag == self.skip_tag:
                self.skip += 1
            return
        a = dict(attrs)
        if _skippable(tag, a):
            if tag in BLOCK_TAGS or tag in SKIP_TAGS:
                self.flush()
            self.skip, self.skip_tag = 1, tag
            return
        if tag in BLOCK_TAGS:
            self.flush()
            if self.stack and self.stack[-1] in CLOSES_SAME.get(tag, ()):
                self.stack.pop()
            if tag in CONTAINER_TAGS:
                self.depth += 1
            self.stack.append(tag)
            self.start_depth = self.depth
            if tag in HEADINGS:
                self.level = HEADINGS[tag]
            elif tag == "li":
                self.prefix = "- "
            elif tag == "pre":
                self.in_pre = True
        elif tag in ("td", "th") and self.buf and not self.in_pre:
            self.buf.append(" | ")
        elif tag == "br":
            self.buf.append("\n" if self.in_pre else " ")
        if a.get("id") and tag not in ("link", "meta"):
            self.ids.append(a["id"])
            if tag in BLOCK_TAGS and not self.id_tag:
                self.id_tag = tag
        if tag == "a" and a.get("name"):
            self.ids.append(a["name"])
        if not self.buf:
            self.start_depth = self.depth

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip_tag:
                self.skip -= 1
            return
        if tag in BLOCK_TAGS:
            self.flush()
            self.in_pre = self.in_pre and tag != "pre"
            if tag in self.stack:
                while self.stack.pop() != tag:
                    pass
            if tag in CONTAINER_TAGS and self.depth:
                self.depth -= 1
            self.start_depth = self.depth

    def handle_data(self, data):
        if self.skip:
            return
        if not self.buf:
            self.start_depth = self.depth
        self.buf.append(data)

    def close(self):
        super().close()
        self.flush()


def html_to_text(html: str) -> List[Block]:
    """Page HTML -> blocks (headings as '#' lines, <pre> fenced, items as '- ')."""
    p = _TextParser()
    p.feed(html)
    p.close()
    return p.blocks


def entry_location(path: str) -> Tuple[str, Optional[str]]:
    """Index path -> (page file, anchor or None): marker tags dropped, file decoded."""
    path = re.sub(r"<dash_entry_[^>]*>", "", path)
    file_part, sep, anchor = path.partition("#")
    return unquote(file_part), (anchor if sep and anchor else None)


def trim_to_anchor(blocks: List[Block], anchor: Optional[str]) -> List[str]:
    """Lines of the section the anchor names; whole page if none or not found."""
    def lines_of(bs):
        return [ln for b in bs for ln in b.text.split("\n")]

    if not anchor:
        return lines_of(blocks)
    want = {anchor, unquote(anchor)}
    start = None
    for i, b in enumerate(blocks):
        if any(x in want or unquote(x) in want for x in b.ids):
            start = i
            break
    if start is None:
        return ["note: anchor not found (%s); showing the whole page" % anchor] \
            + lines_of(blocks)
    first = blocks[start]
    end = len(blocks)
    for j in range(start + 1, len(blocks)):
        b = blocks[j]
        if first.level:
            stop = b.level and b.level <= first.level
        else:
            stop = (b.level or b.depth < first.depth
                    or (b.tag == first.tag and b.ids and b.depth <= first.depth))
        if stop:
            end = j
            break
    return lines_of(blocks[start:end])


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError("%r: must be an integer >= 1" % text)
    return n


def parse_page_ref(ref: str) -> Optional[Tuple[str, str]]:
    """'<Docset>:page:<path>[#anchor]' -> (name, path[#anchor]), else None."""
    name, sep, path = ref.partition(":page:")
    if not sep or not name or not path:
        return None
    return name, path


def page_file(ds, file_part) -> str:
    """Absolute path of a page file inside the docset's Documents; CLIError 5."""
    docs = os.path.join(ds.path, "Contents", "Resources", "Documents")
    page = os.path.normpath(os.path.join(docs, *file_part.split("/")))
    try:
        inside = os.path.commonpath([docs, page]) == docs
    except ValueError:
        inside = False
    if not inside or not os.path.isfile(page):
        raise CLIError("page file not found: %s" % page, 5)
    return page


def read_page_blocks(ds, file_part) -> List[Block]:
    with open(page_file(ds, file_part), "rb") as f:
        return html_to_text(f.read().decode("utf-8", errors="replace"))


def _print_lines(lines, args):
    if not args.full:
        lines = cap_lines(lines, args.max_lines,
                          "raise --max-lines or use --full for the whole section")
    for line in lines:
        print(line)


def cmd_show(args):
    page_ref = parse_page_ref(args.ref)
    name, entry_id = page_ref if page_ref else parse_ref(args.ref)
    store = require_store(args)
    ds = next((d for d in find_docsets(store) if d.name == name), None)
    if ds is None:
        raise CLIError("unknown docset %r (see: docset.py list)" % name, 5)
    if page_ref:
        file_part, sep, anchor = entry_id.partition("#")
        blocks = read_page_blocks(ds, file_part)
        _print_lines(trim_to_anchor(blocks, anchor if sep and anchor else None), args)
        if not args.no_notes:
            for line in general_notes(store, name):
                print(line)
        return 0
    entry = next(iter_entries(ds, entry_id=entry_id), None)
    if entry is None:
        raise CLIError("no entry %s in docset %s" % (args.ref, name), 5)
    _id, entry_name, entry_type, path = entry
    if re.match(r"https?://", path, re.I):
        print("online-only entry: " + path)
        return 0
    file_part, anchor = entry_location(path)
    lines = trim_to_anchor(read_page_blocks(ds, file_part), anchor)
    _print_lines(lines, args)
    if not args.no_notes:
        for line in notes_for(store, name, entry_name, entry_type):
            print(line)
        _p, text = _read_notes(store, name)
        for w in size_warnings(text or ""):
            print("warning: notes: " + w, file=sys.stderr)
    return 0


def cmd_list(args):
    store = require_store(args)
    docs = find_docsets(store)
    if not docs:
        print("no docsets found in %s" % store.path)
        return 0
    for d in docs:
        origin = ("foreign (%s)" % os.path.dirname(d.path) if d.foreign
                  else d.source or "unknown")
        line = "%s  %s  %s  %d entries  %s" % (
            d.name, origin, d.version or "-", d.entry_count,
            "full" if d.full_size else "small")
        if d.clashes:
            line += "  (also in %s; store copy used)" % ", ".join(d.clashes)
        print(line)
    return 0


NOTES_GENERAL_MAX = 50
NOTES_SECTION_MAX = 100
NOTES_TOTAL_MAX = 2000
_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_TYPED = re.compile(r"^(.*?)\s+\(([^()]+)\)$")  # needs a space and a type


def notes_path(store, docset_name) -> str:
    """Notes always live in the script's own store, also for foreign docsets."""
    if (not docset_name or "/" in docset_name or "\\" in docset_name
            or ".." in docset_name):
        raise CLIError("invalid docset name %r" % (docset_name,), 2)
    root = store if isinstance(store, str) else store.path
    return os.path.join(root, "notes", docset_name + ".md")


def parse_notes(text):
    """(general lines, {lowercased heading: [(type or None, lines)]})."""
    general: List[str] = []
    sections: dict = {}
    cur = None  # None = general; else the list the lines go to
    seen_content = False
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            heading = m.group(1)
            typ = None
            tm = _TYPED.match(heading)
            if tm:
                heading, typ = tm.group(1).strip(), tm.group(2).strip() or None
            if heading.lower() == "general" and typ is None:
                cur = general
            else:
                cur = []
                sections.setdefault(heading.lower(), []).append((typ, cur))
            seen_content = True
            continue
        if cur is None:
            if not line.strip():
                continue  # blank lines before any content
            if not seen_content and line.startswith("# "):
                seen_content = True  # leading title line
                continue
            cur = general
        if line.strip() or cur:
            seen_content = True
            cur.append(line)
    return general, sections


def _read_notes(store, docset_name):
    path = notes_path(store, docset_name)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return path, f.read()
    except OSError:
        return path, None


def notes_for(store, docset_name, entry_name, entry_type) -> List[str]:
    path, text = _read_notes(store, docset_name)
    if text is None:
        return []
    general, sections = parse_notes(text)
    body = []
    if any(l.strip() for l in general):
        body += ["## General"] + general
    want = entry_name.lower()
    for key, items in sections.items():
        for typ, lines in items:
            hit = (key == want and (typ is None or typ.lower() == (entry_type or "").lower())) \
                or (typ is not None and "%s (%s)" % (key, typ.lower()) == want)
            if hit and any(l.strip() for l in lines):
                body += ["## %s%s" % (entry_name, "" if typ is None or key != want
                                      else " (%s)" % typ)] + lines
    if not body:
        return []
    return ["--- notes (%s) ---" % path] + body


def general_notes(store, docset_name) -> List[str]:
    path, text = _read_notes(store, docset_name)
    if text is None:
        return []
    general, _ = parse_notes(text)
    if not any(l.strip() for l in general):
        return []
    return ["--- notes (%s) ---" % path, "## General"] + general


def size_warnings(text) -> List[str]:
    general, sections = parse_notes(text)
    warns = []
    if len(general) > NOTES_GENERAL_MAX:
        warns.append("General notes are %d lines (limit %d); trim them"
                     % (len(general), NOTES_GENERAL_MAX))
    for name, items in sections.items():
        for typ, lines in items:
            if len(lines) > NOTES_SECTION_MAX:
                warns.append("section %r is %d lines (limit %d); trim it" % (
                    name + (" (%s)" % typ if typ else ""), len(lines),
                    NOTES_SECTION_MAX))
    total = len(text.splitlines())
    if total > NOTES_TOTAL_MAX:
        warns.append("notes file is %d lines (limit %s); trim it"
                     % (total, format(NOTES_TOTAL_MAX, ",")))
    return warns


def check_notes(text, entry_names) -> List[str]:
    warns = size_warnings(text)
    _, sections = parse_notes(text)
    for name, items in sections.items():
        for typ, _lines in items:
            full = "%s (%s)" % (name, typ.lower()) if typ else name
            if name not in entry_names and full not in entry_names:
                warns.append("section %r matches no entry in the docset" % full)
    return warns


def cmd_notes(args):
    store = require_store(args)
    notes_path(store, args.docset)  # rejects names that are not plain names
    ds = next((d for d in find_docsets(store) if d.name == args.docset), None)
    if ds is None:
        raise CLIError("unknown docset %r (see: docset.py list)" % args.docset, 5)
    path = notes_path(store, ds.name)
    if args.path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        print(path)
        return 0
    _, text = _read_notes(store, ds.name)
    if args.check:
        if text is None:
            print("no notes file: " + path)
            return 0
        names = {n.lower() for _i, n, _t, _p in iter_entries(ds)}
        warns = check_notes(text, names)
        for w in warns:
            print("warning: " + w)
        if not warns:
            print("ok: %s" % path)
        return 1 if warns else 0
    if text is None:
        print("no notes file yet for %s (it would be %s)" % (ds.name, path))
    else:
        sys.stdout.write(text)
    return 0


FTS_SNIPPET_TOKENS = 14


def fts_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61')")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        return False


def fts_path(store, name) -> str:
    return os.path.join(meta_dir(store), "fts", name + ".sqlite")


def docset_stamp(ds) -> str:
    """Staleness key: installed version, else the index file's mtime (int)."""
    if ds.version:
        return str(ds.version)
    try:
        return str(int(os.path.getmtime(index_path(ds.path))))
    except OSError:
        return ""


def _stored_stamp(db):
    if not os.path.isfile(db):
        return None
    try:
        con = _open_ro(db)
        try:
            row = con.execute(
                "SELECT value FROM meta WHERE key='docset_version'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def build_fts(store, ds) -> int:
    """(Re)build the docset's full-text index; return the pages indexed."""
    pages = {}  # page file -> [entry ids]
    for entry_id, _n, _t, path in iter_entries(ds):
        if re.match(r"https?://", path, re.I):
            continue
        file_part, _anchor = entry_location(path)
        if file_part:
            pages.setdefault(file_part, []).append(entry_id)
    db = fts_path(store, ds.name)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    tmp = db + ".tmp"
    if os.path.exists(tmp):
        os.unlink(tmp)
    con = sqlite3.connect(tmp)
    count = 0
    try:
        con.executescript(
            "CREATE VIRTUAL TABLE pages USING fts5(path UNINDEXED, text, "
            "tokenize='unicode61');"
            "CREATE TABLE page_entries(path TEXT, entry_id INTEGER);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
        for file_part, ids in pages.items():
            try:
                blocks = read_page_blocks(ds, file_part)
            except (CLIError, OSError):
                continue
            text = "\n".join(b.text for b in blocks)
            con.execute("INSERT INTO pages(path, text) VALUES (?, ?)", (file_part, text))
            con.executemany("INSERT INTO page_entries VALUES (?, ?)",
                            [(file_part, i) for i in ids])
            count += 1
        con.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("docset_version", docset_stamp(ds)),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))])
        con.commit()
    except BaseException:
        con.close()
        os.unlink(tmp)
        raise
    con.close()
    os.replace(tmp, db)
    return count


def ensure_fts(store, ds) -> None:
    """Build a missing index; rebuild a stale one (noting it on stderr)."""
    stored = _stored_stamp(fts_path(store, ds.name))
    if stored == docset_stamp(ds):
        return
    if stored is None:
        print("note: building the full-text index for %s (first use; large "
              "docsets take a while; index-text builds it ahead)" % ds.name,
              file=sys.stderr)
    build_fts(store, ds)
    if stored is not None:
        _warn("rebuilt index for %s" % ds.name)


def fts_match_expr(query) -> str:
    """Quote each token as an FTS5 phrase and AND them (user text is data)."""
    return " AND ".join('"%s"' % t.replace('"', '""') for t in query.split())


def _snippet_phrases(snippet) -> List[str]:
    """Phrases around the first match of an FTS snippet (matches marked
    \x02...\x03), longest first: two words before it plus up to three from
    it, then just the latter."""
    m = re.search("\x02", snippet)
    if not m:
        return []
    before = snippet[:m.start()].split("...")[-1].split()[-2:]
    after = re.split(r"\.\.\.|[.!?;:](?:\s|$)|\s-\s",
                     re.sub("[\x02\x03]", "", snippet[m.start():]))[0].split()[:3]
    clean = lambda ws: " ".join(ws).strip(" .,;:!?()").lower()
    return [p for p in dict.fromkeys([clean(before + after), clean(after)]) if p]


def match_anchor(ds, path, query, snippet="") -> Optional[str]:
    """The id nearest before the block the match is in (via the FTS snippet,
    else the first block holding the query words), if any."""
    try:
        blocks = read_page_blocks(ds, path)
    except (CLIError, OSError):
        return None
    words = [w.lower() for w in query.split()]
    if not words:
        return None
    texts = [b.text.lower() for b in blocks]
    last_id, anchor_at = None, []
    for b in blocks:  # nearest id at or before each block
        if b.ids:
            last_id = b.ids[0]
        anchor_at.append(last_id)
    texts = [" ".join(t.split()) for t in texts]
    tests = [(lambda t, p=p: p in t) for p in _snippet_phrases(snippet)]
    tests += [lambda t: all(w in t for w in words), lambda t: words[0] in t]
    for test in tests:
        for i, t in enumerate(texts):
            if anchor_at[i] and test(t):
                return anchor_at[i]
    return None


def fts_search(store, docsets, query, limit) -> List[dict]:
    expr = fts_match_expr(query)
    if not expr:
        return []
    scored = []
    for ds in docsets:
        db = fts_path(store, ds.name)
        try:
            con = _open_ro(db)
            try:
                rows = con.execute(
                    "SELECT path, snippet(pages, 1, char(2), char(3), '...', %d), "
                    "bm25(pages) FROM pages WHERE pages MATCH ? "
                    "ORDER BY bm25(pages) LIMIT ?" % FTS_SNIPPET_TOKENS,
                    (expr, limit)).fetchall()
                for path, snip, score in rows:
                    ref = "%s:page:%s" % (ds.name, path)
                    anchor = match_anchor(ds, path, query, snip)  # \x02 marks matches
                    if anchor:
                        ref += "#" + quote(anchor, safe=":/()$")
                    scored.append((score, ds.name, path, {
                        "ref": ref, "docset": ds.name, "path": path,
                        "snippet": " ".join(snip.split()).replace(
                            "\x02", "[").replace("\x03", "]")}))
            finally:
                con.close()
        except sqlite3.Error as e:
            _warn("skipping %s: %s" % (ds.name, e))
    scored.sort(key=lambda h: h[:3])
    return [h[3] for h in scored[:limit]]


def _need_fts():
    if not fts_available():
        raise CLIError("this Python's sqlite3 has no FTS5 support; full-text "
                       "search is unavailable (docset search still works)", 2)


def cmd_index_text(args):
    _need_fts()
    store = require_store(args)
    all_docs = find_docsets(store)
    by_name = {d.name: d for d in all_docs}
    if not args.args:
        raise CLIError("name the docsets to index", 2)
    for n in args.args:
        if n not in by_name:
            raise CLIError("unknown docset %r (see: docset.py list)" % n, 5)
    for n in dict.fromkeys(args.args):
        count = build_fts(store, by_name[n])
        print("indexed %d pages of %s" % (count, n))
    return 0


def cmd_fts(args):
    if not args.query.strip():
        raise CLIError("empty search query", 2)
    _need_fts()
    store = require_store(args)
    docs = select_docsets(store, find_docsets(store), args.docset or [], args.all)
    for ds in docs:
        ensure_fts(store, ds)
    # text output takes two lines per hit: fetch enough hits to reach the line cap
    limit = args.max_lines if args.json else args.max_lines // 2 + 1
    hits = fts_search(store, docs, args.query, limit)
    if args.json:
        print(json.dumps(hits, indent=2))
        return 0
    if not hits:
        print("no matches for %r" % args.query)
        return 0
    room = max(1, (args.max_lines - 1) // 2) if len(hits) * 2 > args.max_lines else len(hits)
    for h in hits[:room]:
        print(h["ref"])
        print("    " + h["snippet"])
    if len(hits) > room:
        print("... %s more hits cut; raise --max-lines or narrow the query or -d"
              % ("%d" % (len(hits) - room) if len(hits) < limit else "%d or" % (len(hits) - room)))
    return 0


# --- sources, install, update, remove ---------------------------------------

# Verified live 2026-11-14. Official docsets: the *.xml files at the root of
# the Kapeli/feeds repo (GitHub API, branch master); each feed is
# <entry><version>..</version><url>http://MIRROR/feeds/Name.tgz</url>...
# (5 mirrors, http: rewritten to https:; they redirect to kapeli.com).
KAPELI_LIST_URL = "https://api.github.com/repos/Kapeli/feeds/contents/"
KAPELI_FEED_URL = "https://raw.githubusercontent.com/Kapeli/feeds/master/%s.xml"
# User-contributed: JSON index {"docsets": {Key: {name, archive, version}}};
# download = USER_BASE_URL + Key + "/" + archive.
USER_BASE_URL = "https://kapeli.com/feeds/zzz/user_contributed/build/"
USER_INDEX_URL = USER_BASE_URL + "index.json"
# Cheat sheets: no index; names = cheatsheets/*.rb in Kapeli/cheatsheets;
# no version, so the HTTP Last-Modified header of the archive stands in.
CHEAT_LIST_URL = "https://api.github.com/repos/Kapeli/cheatsheets/contents/cheatsheets"
CHEAT_URL = "https://kapeli.com/feeds/zzz/cheatsheets/%s.tgz"

# Cheat-sheet index (Kapeli's own; trailing commas must be stripped):
# {"cheatsheets": {Key: {name, version, aliases}}}; download = CHEAT_URL % Key.
CHEAT_INDEX_URL = "https://kapeli.com/feeds/zzz/cheatsheets/cheat.json"
# Older official versions (from zealdocs/backend src/mirror-url.ts):
# https://<mirror>/feeds/zzz/versions/<Feed>/<version>/<Feed>.tgz
VERSIONED_PATH = "/feeds/zzz/versions/%s/%s/%s.tgz"
# Zeal's docset manifest (raw GitHub): {ZealName: {title, source?: feed name,
# versionPrefix?, extra?: {keywords}}}; e.g. Python_3 = feed Python, "3.".
ZEAL_MANIFEST_URL = "https://raw.githubusercontent.com/zealdocs/backend/main/docsets.json"
# Zeal's combined catalog: a best-effort public service with no stability
# promise. Used only when every other source of a list has failed, checked
# at most weekly (conditional request), never retried within a day of a
# failure, and cached without its icons. Entries: {name, title, sourceId
# (com.kapeli.dash|.contrib|.cheatsheet), versions, archive?}.
ZEAL_CATALOG_URL = "https://api.zealdocs.org/_api/v1/catalog.json"
ZEAL_MAX_AGE = 7 * 86400
RETRY_AFTER_FAILURE = 86400

SOURCE_NAMES = ("kapeli", "user", "cheat")
CACHE_MAX_AGE = 7 * 86400
USER_AGENT = f"dash-docset/{VERSION}"
NET_TIMEOUT = 60
UNKNOWN_VERSION = "unknown"


class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class ArchiveError(Exception):
    pass


class AmbiguousName(CLIError):
    def __init__(self, message):
        super().__init__(message, 6)


@dataclass
class Feed:
    name: str
    source: str
    version: str
    urls: List[str]
    aliases: List[str] = field(default_factory=list)  # titles, search keywords
    pin: str = ""  # version prefix the user asked for (kapeli only)


def _https(url):
    return "https://" + url[len("http://"):] if url.lower().startswith("http://") else url


def _pin_matches(version, pin) -> bool:
    return version == pin or version.startswith(pin if pin.endswith(".") else pin + ".")


def parse_kapeli_xml(text: str, name: str, pin: str = "") -> Feed:
    """Feed for the newest version, or the newest matching the pin prefix."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError("bad feed XML for %s: %s" % (name, e))
    version = (root.findtext("version") or "").strip()
    urls = [_https(u.text.strip()) for u in root.findall("url") if u.text and u.text.strip()]
    if not urls:
        raise ValueError("feed %s lists no download URL" % name)
    if not pin or _pin_matches(version, pin):
        return Feed(name, "kapeli", version, urls, pin=pin)
    others = [(v.findtext("name") or "").strip()
              for v in root.findall("other-versions/version")]
    picked = next((v for v in others if v and _pin_matches(v, pin)), None)
    if picked is None:
        shown = ", ".join(v for v in others[:12] if v) or "none listed"
        raise CLIError("kapeli docset %s has no version %s (versions: %s%s)" % (
            name, pin, shown, ", ..." if len(others) > 12 else ""), 5)
    hosts = list(dict.fromkeys(urlsplit(u).netloc for u in urls))
    return Feed(name, "kapeli", picked,
                ["https://" + h + VERSIONED_PATH % (name, picked, name) for h in hosts],
                pin=pin)


def parse_index_json(data: dict, source: str, base_url: str) -> List[Feed]:
    feeds = []
    for key, d in (data.get("docsets") or {}).items():
        if not isinstance(d, dict) or not d.get("archive"):
            continue
        feeds.append(Feed(str(d.get("name") or key), source, str(d.get("version") or ""),
                          [base_url + key + "/" + d["archive"]]))
    return feeds


def _request(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method,
                                 headers=dict(headers or {}, **{"User-Agent": USER_AGENT}))
    try:
        return urllib.request.urlopen(req, timeout=NET_TIMEOUT)
    except urllib.error.HTTPError as e:
        raise FetchError("HTTP %d for %s" % (e.code, url), e.code)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise FetchError("cannot reach %s: %s" % (url, getattr(e, "reason", e)))


def fetch(url: str) -> bytes:
    """GET url (redirects followed). The only function that reads the network."""
    with _request(url) as r:
        try:
            return r.read()
        except (OSError, http.client.HTTPException) as e:
            raise FetchError("download of %s failed: %s" % (url, e))


def fetch_cond(url: str, etag=None, last_modified=None):
    """Conditional GET: (body, etag, last_modified); body None on 304."""
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        r = _request(url, headers=headers)
    except FetchError as e:
        if e.status == 304:
            return None, etag, last_modified
        raise
    with r:
        try:
            body = r.read()
        except (OSError, http.client.HTTPException) as e:
            raise FetchError("download of %s failed: %s" % (url, e))
        return body, r.headers.get("ETag"), r.headers.get("Last-Modified")


def download(url: str, dest: str) -> None:
    """Stream url to the file dest (archives are 100+ MB)."""
    with _request(url) as r:
        try:
            with open(dest, "wb") as out:
                shutil.copyfileobj(r, out, 1 << 20)
        except (OSError, http.client.HTTPException) as e:
            raise FetchError("download of %s failed: %s" % (url, e))


def head_last_modified(url: str) -> Optional[str]:
    """Last-Modified of url, None when unavailable; FetchError only for a 404."""
    try:
        with _request(url, "HEAD") as r:
            return r.headers.get("Last-Modified")
    except FetchError as e:
        if e.status == 404:
            raise
        return None


def _cache_path(store):
    return os.path.join(meta_dir(store), "cache", "sources.json")


def _list_names(url, suffix):
    items = json.loads(fetch(url).decode("utf-8"))
    return sorted(i["name"][:-len(suffix)] for i in items
                  if isinstance(i, dict) and i.get("type", "file") == "file"
                  and str(i.get("name", "")).endswith(suffix))


def cached_get(store, key, url, max_age, force=False, transform=None) -> bytes:
    """Body of url, kept in the cache with its ETag/Last-Modified.

    Re-checked at most every max_age seconds (force skips that wait), with a
    conditional request so an unchanged file is not downloaded again; after
    a failure, not retried for RETRY_AFTER_FAILURE (the cached copy, if any,
    is used meanwhile). transform(bytes) shrinks a new body before saving."""
    d = os.path.join(meta_dir(store), "cache")
    body_p = os.path.join(d, key + ".body")
    meta_p = os.path.join(d, key + ".meta.json")
    try:
        meta = _load_json(meta_p) if os.path.isfile(meta_p) else {}
    except CLIError:
        meta = {}
    have = os.path.isfile(body_p)
    now = time.time()

    def cached():
        with open(body_p, "rb") as f:
            return f.read()

    if have and not force and 0 <= now - meta.get("checked", -max_age - 1) < max_age:
        return cached()
    failed = meta.get("failed")
    if isinstance(failed, (int, float)) and 0 <= now - failed < RETRY_AFTER_FAILURE:
        if have:
            return cached()
        raise FetchError("%s failed less than a day ago (%s); not retrying yet"
                         % (url, meta.get("error", "")))
    os.makedirs(d, exist_ok=True)
    try:
        body, etag, lm = fetch_cond(url, meta.get("etag") if have else None,
                                    meta.get("last_modified") if have else None)
        if body is not None and transform:
            body = transform(body)
    except (FetchError, ValueError) as e:
        meta.update(failed=now, error=str(e))
        _write_json(meta_p, meta)
        if have:
            _warn("using the cached copy of %s; refresh failed: %s" % (url, e))
            return cached()
        raise
    if body is not None:
        tmp = body_p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, body_p)
        meta = {"etag": etag, "last_modified": lm}
    meta.pop("failed", None)
    meta.pop("error", None)
    meta["checked"] = now
    _write_json(meta_p, meta)
    return body if body is not None else cached()


def _slim_catalog(body: bytes) -> bytes:
    """Zeal catalog without icons and other fields we never read."""
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Zeal catalog is not a list")
    keep = ("name", "title", "sourceId", "versions", "archive")
    return json.dumps([{k: e.get(k) for k in keep if k in e}
                       for e in data if isinstance(e, dict) and e.get("name")]).encode()


def zeal_catalog(store) -> List[dict]:
    """Last resort only (see ZEAL_CATALOG_URL); never forced to refresh."""
    return json.loads(cached_get(store, "zeal-catalog", ZEAL_CATALOG_URL,
                                 ZEAL_MAX_AGE, transform=_slim_catalog).decode("utf-8"))


def zeal_manifest(store, refresh=False) -> dict:
    data = json.loads(cached_get(store, "zeal-manifest", ZEAL_MANIFEST_URL,
                                 CACHE_MAX_AGE, force=refresh).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Zeal manifest is not an object")
    return data


def cheat_index(store, refresh=False) -> dict:
    text = cached_get(store, "cheat-index", CHEAT_INDEX_URL, CACHE_MAX_AGE,
                      force=refresh).decode("utf-8")
    data = json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
    sheets = data.get("cheatsheets") if isinstance(data, dict) else None
    if not isinstance(sheets, dict):
        raise ValueError("cheat sheet index has an unexpected shape")
    return sheets


def _note(msg):
    print("note: " + msg, file=sys.stderr)


def _first_version(e) -> str:
    return next((str(v) for v in e.get("versions") or [] if v), "")


def _catalog_feeds(store, source_id):
    return [e for e in zeal_catalog(store) if e.get("sourceId") == source_id]


_SOURCE_ERRORS = (FetchError, ValueError, KeyError, TypeError, AttributeError, CLIError)


def _kapeli_feeds(store, refresh):
    names: dict = {}
    errors = []
    github_failed = [False]
    try:
        for n in _list_names(KAPELI_LIST_URL, ".xml"):
            names.setdefault(n, [])
    except _SOURCE_ERRORS as e:
        errors.append(str(e))
        github_failed[0] = True
    try:
        for key, m in zeal_manifest(store, refresh).items():
            if not isinstance(m, dict):
                continue
            al = [m.get("title")] + list((m.get("extra") or {}).get("keywords") or [])
            names.setdefault(key, []).extend(str(a) for a in al if a)
            if m.get("source"):
                names.setdefault(str(m["source"]), [])
    except _SOURCE_ERRORS as e:
        errors.append(str(e))
    if not names:
        try:
            for e in _catalog_feeds(store, "com.kapeli.dash"):
                names.setdefault(e["name"], []).extend([e["title"]] if e.get("title") else [])
            _note("official docset list from Zeal's catalog (other sources unavailable)")
        except _SOURCE_ERRORS as e:
            errors.append("Zeal catalog: %s" % e)
    elif github_failed[0] and len(errors) == 1:
        _note("official docset list from Zeal's manifest (GitHub API unavailable)")
    if not names:
        raise FetchError("; ".join(errors))
    return [Feed(n, "kapeli", "", [], sorted(set(a for a in al if a != n)))
            for n, al in names.items()]


def _cheat_feeds(store, refresh):
    errors = []
    try:
        return [Feed(k, "cheat", str(v.get("version") or ""), [CHEAT_URL % quote(k)],
                     [str(a) for a in [v.get("name")] + list(v.get("aliases") or [])
                      if a and a != k])
                for k, v in cheat_index(store, refresh).items() if isinstance(v, dict)]
    except _SOURCE_ERRORS as e:
        errors.append(str(e))
    try:
        feeds = [Feed(n, "cheat", "", []) for n in _list_names(CHEAT_LIST_URL, ".rb")]
        _note("cheat sheet list from the GitHub API (Kapeli's cheat.json unavailable)")
        return feeds
    except _SOURCE_ERRORS as e:
        errors.append(str(e))
    try:
        feeds = [Feed(e["name"], "cheat", _first_version(e), [CHEAT_URL % quote(e["name"])],
                      [e["title"]] if e.get("title") else [])
                 for e in _catalog_feeds(store, "com.kapeli.cheatsheet")]
        _note("cheat sheet list from Zeal's catalog (other sources unavailable)")
        return feeds
    except _SOURCE_ERRORS as e:
        errors.append("Zeal catalog: %s" % e)
    raise FetchError("; ".join(errors))


def _user_feeds(store):
    try:
        data = json.loads(fetch(USER_INDEX_URL).decode("utf-8"))
        return parse_index_json(data, "user", USER_BASE_URL)
    except _SOURCE_ERRORS as first:
        try:
            feeds = [Feed(str(e.get("title") or e["name"]), "user", _first_version(e),
                          [USER_BASE_URL + e["name"] + "/" + e["archive"]])
                     for e in _catalog_feeds(store, "com.kapeli.contrib") if e.get("archive")]
            _note("user-contributed list from Zeal's catalog (Kapeli's index unavailable)")
            return feeds
        except _SOURCE_ERRORS as e:
            raise FetchError("%s; Zeal catalog: %s" % (first, e))


def _fetch_source(store, source, refresh):
    if source == "kapeli":
        return _kapeli_feeds(store, refresh)
    if source == "cheat":
        return _cheat_feeds(store, refresh)
    return _user_feeds(store)


def load_sources(store, refresh: bool, sources=SOURCE_NAMES,
                 failed: Optional[list] = None) -> List[Feed]:
    """Feeds of each source, cached per source for 7 days; stale cache on failure.

    Sources with neither a fresh list nor a cache are appended to `failed`."""
    path = _cache_path(store)
    try:
        cache = _load_json(path) if os.path.isfile(path) else {}
    except CLIError:
        cache = {}
    now = time.time()
    feeds, errors, changed = [], [], False
    for source in sources:
        entry = cache.get(source)
        fresh = (entry and not refresh
                 and 0 <= now - entry.get("fetched", 0) < CACHE_MAX_AGE)
        if not fresh:
            try:
                entry = {"fetched": now,
                         "feeds": [vars(f) for f in _fetch_source(store, source, refresh)]}
                cache[source] = entry
                changed = True
            except (FetchError, ValueError, KeyError, TypeError) as e:
                errors.append("%s: %s" % (source, e))
                if entry:
                    _warn("using the cached %s list; refresh failed: %s" % (source, e))
                else:
                    _warn("cannot load the %s list: %s" % (source, e))
                    if failed is not None:
                        failed.append(source)
                    continue
        feeds.extend(Feed(f["name"], f["source"], f["version"], list(f["urls"]),
                          list(f.get("aliases") or []))
                     for f in entry["feeds"])
    if changed:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_json(path, cache)
    if errors and not feeds:
        raise CLIError("could not load any source list (%s)" % "; ".join(errors), 7)
    return feeds


def _norm(name):
    return re.sub(r"[\s_]+", "_", name.strip().lower())


def _name_from_url(url, source):
    """Feed name from a download URL: Name.tgz, or build/<Key>/<archive>."""
    parts = url.rstrip("/").split("/")
    if source == "user":
        return parts[-2]
    return parts[-1][:-len(".tgz")] if parts[-1].endswith(".tgz") else parts[-1]


PREFIX_HINT = ("kapeli:Name for official docsets (no version suffix: "
               "kapeli:Python, kapeli:NodeJS, kapeli:Django), cheat:Name for "
               "cheat sheets (cheat:Git), user:Name for user-contributed")


def _suggest(store, source, name) -> List[str]:
    """Likely intended names for a missing kapeli/cheat feed."""
    out = []
    try:
        cache = _load_json(_cache_path(store))
        names = [f["name"] for f in cache.get(source, {}).get("feeds", [])]
    except (CLIError, OSError, KeyError, TypeError, AttributeError):
        names = []
    if names:
        import difflib
        out += difflib.get_close_matches(name, names, n=3, cutoff=0.6)
    base = re.sub(r"[\s_-]*\d+(\.\d+)*$", "", name)
    if base and base != name and base not in out:
        if names:
            if base in names:
                out.insert(0, base)
        elif source == "kapeli":
            try:
                fetch(KAPELI_FEED_URL % quote(base))
                out.insert(0, base)
            except (FetchError, ValueError, OSError):
                pass
    return ["%s:%s" % (source, n) for n in out]


def resolve_feed(store, source, name, user_feeds=None) -> Feed:
    """Complete feed for source:name without listing the whole source (Ruling 8).

    kapeli names may end in @VERSION (a prefix such as 3.12) and may be Zeal
    names (Python_3 = the Python feed limited to 3.x)."""
    name, at, pin = name.partition("@")
    if at and (source != "kapeli" or not re.match(r"^[0-9A-Za-z][0-9A-Za-z._-]*$", pin)):
        raise CLIError("a version pin (NAME@VERSION) works only for kapeli: names, "
                       "and VERSION must look like 3.12", 2)
    if source in ("kapeli", "cheat") and (
            not re.match(r"^[A-Za-z0-9][A-Za-z0-9._ +-]*$", name) or ".." in name):
        raise CLIError("invalid docset name %r" % name, 2)
    try:
        if source == "kapeli":
            return _kapeli_feed(store, name, pin)
        if source == "cheat":
            url = CHEAT_URL % quote(name)
            try:
                sheets = cheat_index(store)
                key = next((k for k in sheets if k.lower() == name.lower()), None)
                if key and isinstance(sheets[key], dict) and sheets[key].get("version"):
                    return Feed(key, "cheat", str(sheets[key]["version"]),
                                [CHEAT_URL % quote(key)])
            except _SOURCE_ERRORS:
                pass  # fall back to the archive's Last-Modified date
            return Feed(name, "cheat", head_last_modified(url) or UNKNOWN_VERSION, [url])
        if user_feeds is None:
            user_feeds = load_sources(store, False, ("user",))
        for f in user_feeds:
            if f.name == name or _norm(f.name) == _norm(name):
                return f
        raise CLIError("no %s docset named %r (see: docset.py sources %s)"
                       % (source, name, name), 5)
    except FetchError as e:
        if e.status == 404:
            sugg = _suggest(store, source, name)
            others = [s for s in SOURCE_NAMES if s != source]
            raise CLIError("%s docset %r not found (%s). %s" % (
                source, name, e,
                ("Did you mean %s? " % " or ".join(sugg) if sugg else "")
                + "Or try %s:%s or %s:%s." % (others[0], name, others[1], name)), 5)
        raise CLIError(str(e), 7)
    except ValueError as e:
        raise CLIError(str(e), 7)


def _bad_member_path(name):
    n = name.replace("\\", "/")
    return (n.startswith("/") or re.match(r"^[A-Za-z]:", n) is not None
            or ".." in n.split("/"))


def _inside(root, path):
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def safe_extract(tgz_path: str, dest: str) -> str:
    """Extract a gzip tar holding one .docset into dest; return that folder.

    Rejects absolute or `..` paths, links leaving dest, device files and
    fifos, non-gzip input and archives without exactly one top-level
    .docset; ArchiveError, and nothing is extracted unless all members pass."""
    root = os.path.realpath(dest)
    try:
        with open(tgz_path, "rb") as f:
            if f.read(2) != b"\x1f\x8b":
                raise ArchiveError("not a gzip archive")
        with tarfile.open(tgz_path, "r:gz") as tar:
            members = tar.getmembers()
            tops = set()
            for m in members:
                if _bad_member_path(m.name):
                    raise ArchiveError("unsafe path in archive: %r" % m.name)
                parts = [p for p in m.name.replace("\\", "/").split("/") if p not in ("", ".")]
                if not parts:
                    continue
                tops.add(parts[0])
                target = os.path.normpath(os.path.join(root, *parts))
                if m.isdev() or m.isfifo():
                    raise ArchiveError("device or fifo in archive: %r" % m.name)
                if m.issym() or m.islnk():
                    base = root if m.islnk() else os.path.dirname(target)
                    link = m.linkname.replace("\\", "/")
                    if link.startswith("/") or re.match(r"^[A-Za-z]:", link) or not _inside(
                            root, os.path.normpath(os.path.join(base, link))):
                        raise ArchiveError("link leaves the archive: %r -> %r"
                                           % (m.name, m.linkname))
                elif not (m.isfile() or m.isdir()):
                    raise ArchiveError("unsupported member type: %r" % m.name)
            docsets = [t for t in tops if t.endswith(".docset")]
            if len(docsets) != 1 or len(tops) != 1:
                raise ArchiveError("archive must hold exactly one top-level .docset "
                                   "folder (found: %s)" % ", ".join(sorted(tops)))
            if hasattr(tarfile, "data_filter"):
                tar.extractall(dest, members=members, filter="data")
            else:
                tar.extractall(dest, members=members)
    except ArchiveError:
        raise
    except (tarfile.TarError, EOFError, OSError, UnicodeError) as e:
        raise ArchiveError("cannot read archive: %s" % e)
    out = os.path.join(dest, docsets[0])
    for base, dirs, files in os.walk(out):  # belt and braces: nothing resolves outside
        for n in dirs + files:
            if not _inside(root, os.path.realpath(os.path.join(base, n))):
                raise ArchiveError("path resolves outside the extract folder: %r" % n)
    return out


def _download_any(urls, dest):
    errors, statuses = [], []
    for url in urls:
        try:
            download(_https(url), dest)
            return _https(url)
        except FetchError as e:
            errors.append(str(e))
            statuses.append(e.status)
            _warn("mirror failed: %s" % e)
    if errors and all(st == 404 for st in statuses):
        raise CLIError("not found: %s" % "; ".join(errors), 5)
    raise CLIError("download failed on every mirror: %s" % "; ".join(errors), 7)


def install_feed(store, feed: Feed) -> Docset:
    """Download, extract and move the docset into the store; record it."""
    os.makedirs(meta_dir(store), exist_ok=True)
    work = tempfile.mkdtemp(dir=meta_dir(store), prefix="tmp-")
    try:
        archive = os.path.join(work, "download.tgz")
        used = _download_any(feed.urls, archive)
        out = os.path.join(work, "x")
        os.makedirs(out)
        try:
            extracted = safe_extract(archive, out)
        except ArchiveError as e:
            raise CLIError("bad archive from %s: %s" % (used, e), 7)
        name = os.path.basename(extracted)[:-len(".docset")]
        if not os.path.isdir(extracted) or _make_docset(extracted, False, None, None) is None:
            raise CLIError("bad archive from %s: %s.docset has no readable index"
                           % (used, name), 7)
        old_meta = load_installed(store).get(name)
        exists = os.path.isdir(os.path.join(store.path, name + ".docset")) or old_meta
        same = (_norm(name) == _norm(feed.name)
                or (isinstance(old_meta, dict) and old_meta.get("url")
                    and _name_from_url(old_meta["url"], feed.source)
                    == _name_from_url(used, feed.source)))
        if exists and not same:
            raise CLIError("archive for %s holds %s.docset, which would overwrite a "
                           "different docset; not installed" % (feed.name, name), 7)
        final = os.path.join(store.path, name + ".docset")
        backup = os.path.join(work, "old")
        had = os.path.isdir(final)
        if had:
            os.replace(final, backup)
        try:
            os.replace(extracted, final)
        except BaseException:
            if had:
                os.replace(backup, final)
            raise
        installed = load_installed(store)
        installed[name] = {"source": feed.source, "version": feed.version, "url": used,
                           "installed": time.strftime("%Y-%m-%d")}
        if feed.pin:
            installed[name]["pin"] = feed.pin
        save_installed(store, installed)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ds = _make_docset(final, False, feed.source, feed.version)
    if ds is None:
        raise CLIError("installed %s but its index is unreadable" % name, 7)
    return ds


def _kapeli_feed(store, name, pin) -> Feed:
    try:
        return parse_kapeli_xml(fetch(KAPELI_FEED_URL % quote(name)).decode("utf-8"),
                                name, pin)
    except FetchError as e:
        if e.status != 404:
            raise
        try:
            man = zeal_manifest(store)
        except _SOURCE_ERRORS:
            raise e
        key = next((k for k in man if k.lower() == name.lower()), None)
        m = man.get(key) if key else None
        if not isinstance(m, dict) or not (m.get("source") or m.get("versionPrefix")):
            raise e
        feed_name = str(m.get("source") or key)
        pin = pin or str(m.get("versionPrefix") or "")
        return parse_kapeli_xml(fetch(KAPELI_FEED_URL % quote(feed_name)).decode("utf-8"),
                                feed_name, pin)


def install(store, spec: str) -> Docset:
    prefix, sep, name = spec.partition(":")
    if sep and prefix in SOURCE_NAMES and name:
        return install_feed(store, resolve_feed(store, prefix, name))
    failed: List[str] = []
    matches = [f for f in load_sources(store, False, failed=failed)
               if _norm(f.name) == _norm(spec)]
    if not matches:
        where = ("the loaded source lists (the %s list could not be loaded)"
                 % " and ".join(failed) if failed else "any source list")
        raise CLIError("no docset named %r in %s. Try a prefix: %s; or "
                       "docset.py sources %s" % (spec, where, PREFIX_HINT, spec), 5)
    if len(matches) > 1:
        raise AmbiguousName("%r is offered by several sources; name one: %s"
                            % (spec, ", ".join("%s:%s" % (f.source, f.name)
                                               for f in matches)))
    f = matches[0]
    return install_feed(store, resolve_feed(store, f.source, f.name))


def cmd_sources(args):
    store = require_store(args)
    failed: List[str] = []
    feeds = load_sources(store, args.refresh, failed=failed)
    q = _norm(args.query) if args.query else ""
    lines = []
    for f in feeds:
        if q in _norm(f.name) or any(q in _norm(a) for a in f.aliases):
            lines.append("%s:%s%s" % (f.source, f.name,
                                      "  " + f.version if f.version else ""))
    lines.sort()
    if not lines:
        print("no docsets match %r" % (args.query or ""))
    for line in cap_lines(lines, args.max_lines,
                          "raise --max-lines or give a QUERY"):
        print(line)
    if failed:
        print("note: incomplete list: the %s list could not be loaded. "
              "Prefixed installs still work: %s" % (
                  " and ".join(failed), PREFIX_HINT))
        return 7
    return 0


def cmd_install(args):
    store = require_store(args)
    failed = 0
    for spec in args.specs:
        try:
            ds = install(store, spec)
        except CLIError as e:
            if len(args.specs) == 1:
                raise
            print("%s: %s" % (spec, e), file=sys.stderr)
            failed = e.code
            continue
        print("installed %s %s (%d entries)" % (ds.name, ds.version or "", ds.entry_count))
    return failed


def _managed(store, name):
    """The installed.json entry for name, or a CLIError (5 unknown, 2 not ours)."""
    installed = load_installed(store)
    if name in installed and isinstance(installed[name], dict):
        return installed[name]
    if any(d.name == name for d in find_docsets(store)):
        raise CLIError("%s was not installed by docset.py (foreign or hand-copied); "
                       "manage it with the tool that owns it" % name, 2)
    raise CLIError("unknown docset %r (see: docset.py list)" % name, 5)


def cmd_update(args):
    store = require_store(args)
    installed = load_installed(store)
    names = list(dict.fromkeys(args.names)) or sorted(installed)
    metas = {n: _managed(store, n) for n in names}
    if not names:
        print("nothing installed")
        return 0
    user_feeds = None
    failed = 0
    for name in names:
        meta = metas[name]
        try:
            source = meta.get("source")
            if source not in SOURCE_NAMES or not meta.get("url"):
                raise CLIError("%s has no usable source record" % name, 2)
            feed_name = _name_from_url(meta["url"], source)
            if source == "kapeli" and meta.get("pin"):
                feed_name += "@" + meta["pin"]
            if source == "user" and user_feeds is None:
                user_feeds = load_sources(store, True, ("user",))
            feed = next((f for f in (user_feeds or []) if meta["url"] in f.urls), None) \
                or resolve_feed(store, source, feed_name, user_feeds)
            if UNKNOWN_VERSION in (feed.version, meta.get("version")):
                print("%s: version unknown; re-downloading" % name)
            elif feed.version == meta.get("version"):
                print("%s: up to date (%s)" % (name, feed.version or "-"))
                continue
            ds = install_feed(store, feed)
        except CLIError as e:
            print("%s: %s" % (name, e), file=sys.stderr)
            failed = failed or e.code
            continue
        print("%s: updated %s -> %s" % (name, meta.get("version") or "-",
                                        feed.version or "-"))
        _p, text = _read_notes(store, ds.name)
        if text:
            names_ = {n.lower() for _i, n, _t, _p2 in iter_entries(ds)}
            for w in check_notes(text, names_):
                print("warning: notes: " + w)
    return failed


def cmd_remove(args):
    store = require_store(args)
    _managed(store, args.name)
    path = os.path.join(store.path, args.name + ".docset")
    try:
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    except OSError as e:
        raise CLIError("cannot remove %s: %s" % (path, e), 7)
    try:
        os.unlink(fts_path(store, args.name))
    except OSError:
        pass
    installed = load_installed(store)
    installed.pop(args.name, None)
    save_installed(store, installed)
    print("removed %s" % args.name)
    if os.path.exists(notes_path(store, args.name)):
        print("notes kept: " + notes_path(store, args.name))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="docset.py", description=f"dash-docset {VERSION}: {__doc__}",
        epilog="exit codes: 0 ok; 1 notes --check found problems; 2 usage, "
               "unknown name or no FTS5; 3 storage location not set; 4 search "
               "scope too wide (use -d, a project list or --all); 5 not "
               "found; 6 ambiguous name (add a prefix); 7 network, archive or "
               "incomplete source list")
    parser.add_argument("--version", action="version",
                        version=f"dash-docset {VERSION}")
    parser.add_argument("--dir", metavar="PATH",
                        help="use this docset store (overrides DASH_DOCSET_DIR and config)")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, help_text in SUBCOMMANDS.items():
        p = sub.add_parser(name, help=help_text, description=help_text)
        if name == "where":
            p.add_argument("--discover", action="store_true",
                           help="list existing dasht/Zeal/Dash docset folders")
            p.add_argument("--set", metavar="PATH", help="save PATH as the store")
            p.add_argument("--project", action="store_true",
                           help="with --set: write .dash-docset.json in the current folder")
            p.add_argument("--user", action="store_true",
                           help="with --set: write the user config file")
            p.add_argument("--read-from", metavar="DIR", action="append",
                           help="with --set: extra read-only docset folder (repeatable)")
            p.set_defaults(handler=cmd_where)
            continue
        if name == "list":
            p.set_defaults(handler=cmd_list)
            continue
        if name == "sources":
            p.add_argument("query", nargs="?", metavar="QUERY",
                           help="only docsets whose name, title or keywords contain this text")
            p.add_argument("--refresh", action="store_true",
                           help="refetch the source lists (cached for 7 days)")
            p.add_argument("--max-lines", type=positive_int, default=40, metavar="N",
                           help="print at most N lines (default 40)")
            p.set_defaults(handler=cmd_sources)
            continue
        if name == "install":
            p.add_argument("specs", nargs="+", metavar="SPEC",
                           help="[kapeli:|user:|cheat:]Name; a prefix is needed when "
                           "several sources offer the name")
            p.set_defaults(handler=cmd_install)
            continue
        if name == "update":
            p.add_argument("names", nargs="*", metavar="NAME",
                           help="installed docsets to update (default: all)")
            p.set_defaults(handler=cmd_update)
            continue
        if name == "remove":
            p.add_argument("name", metavar="NAME")
            p.set_defaults(handler=cmd_remove)
            continue
        if name == "show":
            p.add_argument("ref", metavar="REF", help="<Docset>:<id> from search, or <Docset>:page:<path>[#anchor] from fts")
            p.add_argument("--full", action="store_true",
                           help="print the whole trimmed section, without the line cap")
            p.add_argument("--max-lines", type=positive_int, default=150, metavar="N",
                           help="print at most N lines (default 150)")
            p.add_argument("--no-notes", action="store_true",
                           help="do not append notes")
            p.set_defaults(handler=cmd_show)
            continue
        if name == "search":
            p.add_argument("query", metavar="QUERY")
            p.add_argument("-d", "--docset", metavar="NAME", action="append",
                           help="search only this docset (repeatable)")
            p.add_argument("--all", action="store_true",
                           help="search every docset (needed when more than 4 "
                           "are full-size and no project list is set)")
            p.add_argument("--type", metavar="TYPE",
                           help="only entries of this type (case-insensitive)")
            p.add_argument("--max-lines", type=positive_int, default=40, metavar="N",
                           help="print at most N results (default 40)")
            p.add_argument("--json", action="store_true",
                           help="print a JSON list of {ref, docset, type, name, rank}")
            p.set_defaults(handler=cmd_search)
            continue
        if name == "fts":
            p.add_argument("query", metavar="QUERY")
            p.add_argument("-d", "--docset", metavar="NAME", action="append",
                           help="search only this docset (repeatable)")
            p.add_argument("--all", action="store_true",
                           help="search every docset (needed when more than 4 "
                           "are full-size and no project list is set)")
            p.add_argument("--max-lines", type=positive_int, default=40, metavar="N",
                           help="print at most N lines (default 40)")
            p.add_argument("--json", action="store_true",
                           help="print a JSON list of {ref, docset, path, snippet}")
            p.set_defaults(handler=cmd_fts)
            continue
        if name == "index-text":
            p.add_argument("args", nargs="*", metavar="DOCSET",
                           help="docsets to (re)build the full-text index for")
            p.set_defaults(handler=cmd_index_text)
            continue
        if name == "notes":
            p.add_argument("docset", metavar="DOCSET")
            g = p.add_mutually_exclusive_group()
            g.add_argument("--check", action="store_true",
                           help="warn about oversized notes and headings matching "
                           "no entry; exit 1 if any")
            g.add_argument("--path", action="store_true",
                           help="print the notes file path, creating notes/ (edit the file "
                                "with normal tools)")
            p.set_defaults(handler=cmd_notes)
            continue
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except CLIError as e:
        print(str(e), file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
