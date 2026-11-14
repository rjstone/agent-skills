#!/usr/bin/env python3
"""Install Dash docsets and search them offline (stdlib only)."""
import argparse
import json
import os
import sys
import pathlib
import re
import sqlite3
import tempfile
from html.parser import HTMLParser
from urllib.parse import unquote
from dataclasses import dataclass, field
from typing import Iterator, List, Mapping, Optional, Tuple

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
    "notes": "read or write notes for a docset",
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
        return 0
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
        if "searchIndex" in _tables(con):
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
        if "searchIndex" in _tables(con):
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
    lines = ["%s:%d  %s  %s  (%s)" % (d, i, t, n, d) for r, _l, n, d, i, t in hits]
    for line in cap_lines(lines, args.max_lines, hint):
        print(line)
    for dname in dict.fromkeys(h[3] for h in hits):
        for line in general_notes(store, dname):
            print(line)
    return 0


@dataclass
class Block:
    level: int        # heading level 1-6, 0 for other blocks
    ids: List[str]    # ids / <a name> seen since the last emitted block
    text: str         # one or more lines
    tag: str          # element that started the block (the id carrier if any)
    depth: int        # open dl/table/ul/ol containers


SKIP_TAGS = {"script", "style", "nav", "header", "footer"}
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
            if tag in SKIP_TAGS:
                self.skip += 1
            return
        if tag in SKIP_TAGS:
            self.flush()
            self.skip = 1
            return
        a = dict(attrs)
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
        if a.get("id"):
            self.ids.append(a["id"])
            if tag in BLOCK_TAGS and not self.id_tag:
                self.id_tag = tag
        if tag == "a" and a.get("name"):
            self.ids.append(a["name"])
        if not self.buf:
            self.start_depth = self.depth

    def handle_endtag(self, tag):
        if self.skip:
            if tag in SKIP_TAGS:
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


def cmd_show(args):
    name, entry_id = parse_ref(args.ref)
    store = require_store(args)
    ds = next((d for d in find_docsets(store) if d.name == name), None)
    if ds is None:
        raise CLIError("unknown docset %r (see: docset.py list)" % name, 5)
    entry = next(iter_entries(ds, entry_id=entry_id), None)
    if entry is None:
        raise CLIError("no entry %s in docset %s" % (args.ref, name), 5)
    _id, entry_name, entry_type, path = entry
    if re.match(r"https?://", path, re.I):
        print("online-only entry: " + path)
        return 0
    file_part, anchor = entry_location(path)
    docs = os.path.join(ds.path, "Contents", "Resources", "Documents")
    page = os.path.normpath(os.path.join(docs, *file_part.split("/")))
    try:
        inside = os.path.commonpath([docs, page]) == docs
    except ValueError:
        inside = False
    if not inside or not os.path.isfile(page):
        raise CLIError("page file not found: %s" % page, 5)
    with open(page, "rb") as f:
        html = f.read().decode("utf-8", errors="replace")
    blocks = html_to_text(html)
    lines = trim_to_anchor(blocks, anchor)
    if not args.full:
        lines = cap_lines(lines, args.max_lines,
                          "raise --max-lines or use --full for the whole section")
    for line in lines:
        print(line)
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
_TYPED = re.compile(r"^(.*?)\s*\(([^()]*)\)$")


def notes_path(store, docset_name) -> str:
    """Notes always live in the script's own store, also for foreign docsets."""
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
        if cur is None and not seen_content and line.startswith("# "):
            seen_content = True  # leading title line
            continue
        if cur is None:
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
    body = list(general)
    for typ, lines in sections.get(entry_name.lower(), []):
        if typ is None or typ.lower() == (entry_type or "").lower():
            body.extend(lines)
    if not any(l.strip() for l in body):
        return []
    return ["--- notes (%s) ---" % path] + body


def general_notes(store, docset_name) -> List[str]:
    path, text = _read_notes(store, docset_name)
    if text is None:
        return []
    general, _ = parse_notes(text)
    if not any(l.strip() for l in general):
        return []
    return ["--- notes (%s) ---" % path] + general


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
    for name in sections:
        if name not in entry_names:
            warns.append("section %r matches no entry in the docset" % name)
    return warns


def cmd_notes(args):
    store = require_store(args)
    ds = next((d for d in find_docsets(store) if d.name == args.docset), None)
    if ds is None:
        raise CLIError("unknown docset %r (see: docset.py list)" % args.docset, 5)
    path = notes_path(store, ds.name)
    if args.path:
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
        return 1 if warns else 0
    if text is None:
        print("no notes file yet for %s (it would be %s)" % (ds.name, path))
    else:
        sys.stdout.write(text)
    return 0


def not_implemented(args):
    print("not implemented: " + args.command, file=sys.stderr)
    return 2


def build_parser():
    parser = argparse.ArgumentParser(prog="docset.py", description=__doc__)
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
        if name == "show":
            p.add_argument("ref", metavar="REF", help="<Docset>:<id> from search")
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
        if name == "notes":
            p.add_argument("docset", metavar="DOCSET")
            g = p.add_mutually_exclusive_group()
            g.add_argument("--check", action="store_true",
                           help="warn about oversized notes and headings matching "
                           "no entry; exit 1 if any")
            g.add_argument("--path", action="store_true",
                           help="print the notes file path (not created)")
            p.set_defaults(handler=cmd_notes)
            continue
        p.add_argument("args", nargs="*")
        p.set_defaults(handler=not_implemented)
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
