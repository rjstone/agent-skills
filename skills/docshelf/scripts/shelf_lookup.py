"""docshelf lookup commands: search, show, fts, index-text."""
import argparse
import contextlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
from urllib.parse import unquote
from typing import Dict, List, Optional, Tuple

import shelf_backends
import shelf_notes
from shelf_render import (_print_lines, _print_page_title,
                          section_headings, section_lines)
from shelf_core import (CLIError, Config, cap_lines, pick_docvol, rank,
                        same_family_note, select_docvols, short_name, warn)

FUZZY_SHOWN = 0  # fuzzy hits shown when exact, prefix or substring hits exist


def _join_query(args):
    """QUERY may be given as several words; join them with single spaces."""
    q = args.query
    args.query = " ".join(q).strip() if isinstance(q, list) else (q or "")


def _fold_bare_entries(hits, no_anchor, page_of):
    """Drop a whole-page entry when an anchored entry with the same short name
    on the same page is also a hit: `show` opens the same section for both
    (it starts a bare entry at the heading named like it). Returns the kept
    hits and {ref: [folded REFs]}; nothing is lost, the REF moves."""
    twin = {}  # (docvol, page, short name) -> ref of first anchored hit
    for h in hits:
        ref = h[4]
        if ref not in no_anchor:
            twin.setdefault((h[3], page_of[ref], short_name(h[2])), ref)
    kept, also = [], {}
    for h in hits:
        ref = h[4]
        target = (twin.get((h[3], page_of[ref], short_name(h[2])))
                  if ref in no_anchor else None)
        if target is not None:
            also.setdefault(target, []).append(ref)
        else:
            kept.append(h)
    return kept, also


def _best_per_word(docs, words, want_type) -> List[Tuple[str, Optional[str]]]:
    """[(word, 'REF  type  name' of its best non-fuzzy entry, or None)], for
    a query whose words are never all in one name (several names at once)."""
    out = []
    for w in dict.fromkeys(words):
        best = None
        for ds in docs:
            for e in ds.entries():
                if want_type is not None and e.type.lower() != want_type:
                    continue
                r = rank(w, e.name)
                if r is not None and short_name(e.name) == w:
                    r = 0
                if r is None or r >= 3:
                    continue
                key = (r, e.anchor is None, len(e.name), e.name, e.ref)
                if best is None or key < best[0]:
                    best = (key, "%s  %s  %s" % (e.ref, e.type, e.name))
        out.append((w, best and best[1]))
    return out


HEADING = "(heading)"  # type shown for a heading inside a page


def _rank_name(query, words, name) -> Optional[int]:
    """rank(), plus: several words all in the name, in any order, rank like a
    substring (2); 'f(a, b)' for query 'f' ranks as exact (0)."""
    r = rank(query, name)
    if (r is None or r == 3) and len(words) > 1 \
            and all(w in name.lower() for w in words):
        r = 2
    if r and short_name(name) == query.lower():
        r = 0
    return r


def _heading_hits(docs, query, words, page_of, max_rank) -> list:
    """Search hits for headings inside pages ranked at most max_rank (never
    fuzzy), for docvols that index whole sections rather than each function.
    A heading named like an entry ranks like it, so callers that cap
    max_rank below the best entry hit get no duplicates."""
    hits, seen = [], set()
    for ds in docs:
        for page, rows in shelf_notes.docvol_headings(ds).items():
            for name, anchor in rows:
                r = _rank_name(query, words, name)
                ref = ds.make_ref(page, anchor)
                if r is None or r > max_rank or (ref, name) in seen:
                    continue
                seen.add((ref, name))
                page_of[ref] = page
                hits.append((r, len(name), name, ds.name, ref, HEADING))
    return hits


def _print_family_note(docs, args) -> None:
    note = same_family_note(docs)
    if note:
        print(note, file=sys.stderr if args.json else sys.stdout)


def cmd_search(cfg: Config, args: argparse.Namespace) -> int:
    _join_query(args)
    if not args.query:
        raise CLIError("empty search query", 2)
    docs = select_docvols(cfg, shelf_backends.installed_docvols(cfg),
                          args.docvol or [], args.all)
    _print_family_note(docs, args)
    words = args.query.lower().split()
    want_type = args.type.lower() if args.type else None
    hits = []
    no_anchor = set()  # refs of entries that point at a whole page
    page_of: Dict[str, str] = {}  # ref -> page
    for ds in docs:
        for e in ds.entries():
            if want_type is not None and e.type.lower() != want_type:
                continue
            name = e.name
            r = _rank_name(args.query, words, name)
            if r is None:
                continue
            page_of[e.ref] = e.page
            if e.anchor is None:
                no_anchor.add(e.ref)
            hits.append((r, len(name), name, ds.name, e.ref, e.type))
    # headings inside pages: every non-fuzzy one when no entry name matches,
    # only exact ones when entries match just by prefix or substring
    best = min((h[0] for h in hits), default=3)
    only_headings = best == 3
    if want_type is None and best > 0:
        hits += _heading_hits(docs, args.query, words, page_of,
                              2 if only_headings else 0)
    # within a rank, entries with an anchor (a section) before whole pages
    hits.sort(key=lambda h: (h[0], h[4] in no_anchor) + h[1:5])
    hits, also = _fold_bare_entries(hits, no_anchor, page_of)
    hint = "raise --max-lines or narrow the query, -d or --type"
    if args.json:
        items = []
        for r, _l, n, d, ref, t in hits[:args.max_lines]:
            item = {"ref": ref, "docvol": d, "type": t, "name": n, "rank": r}
            if ref in also:
                item["same_section"] = also[ref]
            items.append(item)
        print(json.dumps(items, indent=2))
        return 0
    real = sum(1 for h in hits if h[0] < 3)
    if real and len(hits) - real > FUZZY_SHOWN:
        cut = len(hits) - real - FUZZY_SHOWN
        hits = hits[:real + FUZZY_SHOWN]
    else:
        cut = 0
    lines = []
    if only_headings and hits and hits[0][5] == HEADING:
        lines.append("no entry name matches %r; headings inside pages "
                     "(show REF opens the section):" % args.query)
    for k, (r, _l, n, d, ref, t) in enumerate(hits):
        if r == 3 and (k == 0 or hits[k - 1][0] < 3):
            lines.append("no exact, prefix or substring matches; fuzzy matches "
                         "(letters in order, often unrelated):" if k == 0 else
                         "--- fuzzy matches (letters in order, often unrelated) ---")
        lines.append("%s  %s  %s" % (ref, t, n))
    # silent when a hit holds the query as whole words (asyncio.gather for
    # "gather"): nobody needs the fuzzy ones then
    whole = re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % r"[\W_]+".join(
        re.escape(w) for w in words), re.I)
    if cut and not any(h[0] < 3 and whole.search(h[2]) for h in hits):
        lines.append("... %d fuzzy matches hidden (letters in order only, often "
                     "unrelated)" % cut)
    if not hits:
        each = _best_per_word(docs, words, want_type) if len(words) > 1 else []
        if any(best for _w, best in each):
            lines.append("no matches for %r: search wants all the words in one "
                         "entry name. Best entry for each word:" % args.query)
            for w, best in each:
                lines.append(best or "(no entry name contains %r; fts searches "
                                     "the text inside pages)" % w)
        else:
            lines.append("no matches for %r (%s; fts searches the text inside "
                         "pages)" % (args.query, "entry names only" if want_type
                                     else "entry names and page headings"))
    for line in cap_lines(lines, args.max_lines, hint):
        print(line)
    return 0


def _split_ref(ref):
    name, sep, rest = ref.partition(":")
    if not sep or not name or not rest:
        raise CLIError("bad reference %r (expected <docvol>:<path>[#anchor])"
                       % ref, 2)
    return name, rest


def cmd_show(cfg: Config, args: argparse.Namespace) -> int:
    name, rest = _split_ref(args.ref)
    ds = pick_docvol(shelf_backends.installed_docvols(cfg), name)
    page, anchor, entry = ds.resolve(rest)
    blocks = ds.page_blocks(page, link=lambda href: ds.resolve_href(page, href))
    if anchor:
        want = {anchor, unquote(anchor)}
        if not any(x in want or unquote(x) in want for b in blocks for x in b.ids):
            print("warning: no #%s on %s" % (anchor, page), file=sys.stderr)
            anchor = None
    elif entry is not None:  # no anchor: start at a heading named like the entry
        want_name = short_name(entry.name)
        anchor = next((b.ids[0] for b in blocks if b.level and b.ids
                       and short_name(b.text.lstrip("#").strip()) == want_name),
                      None)
    lines, def_ends = section_lines(blocks, anchor)
    _print_page_title(blocks, lines)
    _print_lines(lines, args, def_ends)
    if not args.no_notes:
        heads = section_headings(blocks, anchor)
        if entry is not None:
            out = shelf_notes.notes_for(cfg, ds, entry.name, entry.type, heads)
        else:
            out = shelf_notes.general_notes(cfg, ds, heads)
        for line in out:
            print(line)
        _p, text = shelf_notes._read_notes(cfg, ds.family)
        for w in shelf_notes.size_warnings(text or ""):
            print("warning: notes: " + w, file=sys.stderr)
    return 0


# --- full-text search ---------------------------------------------------------

FTS_SNIPPET_TOKENS = 14
# Bump when what the index stores changes, so existing indexes are rebuilt.
FTS_FORMAT = 4  # 3: docset footers left out; 4: headers too
FTS_MAX_LINES = 11  # 5 hits (two lines each) plus the "more hits cut" line


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


def _open_ro(path):
    uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def fts_path(ds) -> str:
    return os.path.join(ds.data_dir(), "fts.sqlite")


def fts_stamp(ds) -> str:
    return "%s|fts%d" % (ds.stamp(), FTS_FORMAT)


def _stored_stamp(db):
    if not os.path.isfile(db):
        return None
    try:
        con = _open_ro(db)
        try:
            row = con.execute(
                "SELECT value FROM meta WHERE key='docvol_version'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def build_fts(cfg, ds) -> int:
    """(Re)build the docvol's full-text index; return the pages indexed."""
    refs_on = {}  # page -> [entry REFs]
    for e in ds.entries():
        refs_on.setdefault(e.page, []).append(e.ref)
    db = fts_path(ds)
    try:
        os.makedirs(os.path.dirname(db), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(db), suffix=".tmp")
        os.close(fd)  # sqlite opens it itself; the name is unique per build
    except OSError as e:
        raise CLIError("cannot write the index for %s in %s: %s (set "
                       "DOCSHELF_CACHE_DIR to a writable folder)"
                       % (ds.name, os.path.dirname(db), e), 2)
    con = sqlite3.connect(tmp)
    count = 0
    try:
        con.executescript(
            "CREATE VIRTUAL TABLE pages USING fts5(page UNINDEXED, text, "
            "tokenize='unicode61');"
            "CREATE TABLE page_entries(page TEXT, ref TEXT);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);")
        stamp = fts_stamp(ds)  # before reading, so a change mid-build is seen
        for page in ds.pages():
            try:
                blocks = ds.page_blocks(page)
            except (CLIError, OSError):
                continue
            con.execute("INSERT INTO pages(page, text) VALUES (?, ?)",
                        (page, "\n".join(b.text for b in blocks)))
            con.executemany("INSERT INTO page_entries VALUES (?, ?)",
                            [(page, r) for r in refs_on.get(page, [])])
            count += 1
        con.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("docvol_version", stamp),
            ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))])
        con.commit()
    except BaseException:
        con.close()
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    con.close()
    try:
        os.replace(tmp, db)  # a concurrent build may have won; last one wins
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return count


def ensure_fts(cfg, ds) -> None:
    """Build a missing index; rebuild a stale one (noting it on stderr)."""
    stored = _stored_stamp(fts_path(ds))
    if stored == fts_stamp(ds):
        return
    if stored is None:
        print("note: building the full-text index for %s (first use; large "
              "docvols take a while; index-text builds it ahead)" % ds.name,
              file=sys.stderr)
    build_fts(cfg, ds)
    if stored is not None:
        warn("rebuilt index for %s" % ds.name)


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


def match_anchor(ds, page, query, snippet="") -> Optional[List[str]]:
    """Ids of the nearest block with ids at or before the match (located via
    the FTS snippet, else the first block holding the query words), if any."""
    try:
        blocks = ds.page_blocks(page)
    except (CLIError, OSError):
        return None
    words = [w.lower() for w in query.split()]
    if not words:
        return None
    last_id, anchor_at = None, []
    for b in blocks:  # nearest id at or before each block
        if b.ids:
            last_id = list(b.ids)  # every id of the block: any may be an entry's
        anchor_at.append(last_id)
    texts = [" ".join(b.text.lower().split()) for b in blocks]
    tests = [(lambda t, p=p: p in t) for p in _snippet_phrases(snippet)]
    tests += [lambda t: all(w in t for w in words), lambda t: words[0] in t]
    for test in tests:
        for i, t in enumerate(texts):
            if anchor_at[i] and test(t):
                return anchor_at[i]
    return None


def _unquote_all(text) -> str:
    """URL-decode until stable (anchors are sometimes encoded twice)."""
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    return text


def _anchor_entries(ds) -> dict:
    """{(page, decoded anchor): REF of the first entry there}."""
    found: dict = {}
    for e in ds.entries():
        if e.anchor:
            found.setdefault((e.page, _unquote_all(e.anchor)), e.ref)
    return found


def fts_search(cfg, docvols, query, limit) -> List[dict]:
    expr = fts_match_expr(query)
    if not expr:
        return []
    scored = []
    for ds in docvols:
        entry_at = None  # built on the first hit with an anchor
        try:
            con = _open_ro(fts_path(ds))
            try:
                rows = con.execute(
                    "SELECT page, snippet(pages, 1, char(2), char(3), '...', %d), "
                    "bm25(pages) FROM pages WHERE pages MATCH ? "
                    "ORDER BY bm25(pages) LIMIT ?" % FTS_SNIPPET_TOKENS,
                    (expr, limit)).fetchall()
                for page, snip, score in rows:
                    ids = match_anchor(ds, page, query, snip)  # \x02 marks matches
                    ref = ds.make_ref(page, None)
                    if ids:
                        if entry_at is None:
                            entry_at = _anchor_entries(ds)
                        ref = next((entry_at[(page, _unquote_all(a))] for a in ids
                                    if (page, _unquote_all(a)) in entry_at),
                                   ds.make_ref(page, ids[0]))
                    scored.append((score, ds.name, page, {
                        "ref": ref, "docvol": ds.name, "page": page,
                        "snippet": " ".join(snip.split()).replace(
                            "\x02", "[").replace("\x03", "]")}))
            finally:
                con.close()
        except sqlite3.Error as e:
            warn("skipping %s: %s" % (ds.name, e))
    scored.sort(key=lambda h: h[:3])
    return [h[3] for h in scored[:limit]]


def _need_fts():
    if not fts_available():
        raise CLIError("this Python's sqlite3 has no FTS5 support; full-text "
                       "search is unavailable (entry-name search still works)", 2)


def cmd_index_text(cfg: Config, args: argparse.Namespace) -> int:
    _need_fts()
    all_docs = shelf_backends.installed_docvols(cfg)
    picked = {}
    for n in args.docvol:
        d = pick_docvol(all_docs, n)
        picked[d.name] = d
    for d in picked.values():
        print("indexed %d pages of %s" % (build_fts(cfg, d), d.name))
    return 0


def cmd_fts(cfg: Config, args: argparse.Namespace) -> int:
    _join_query(args)
    if not args.query.strip():
        raise CLIError("empty search query", 2)
    _need_fts()
    docs = select_docvols(cfg, shelf_backends.installed_docvols(cfg),
                          args.docvol or [], args.all)
    _print_family_note(docs, args)
    for ds in docs:
        ensure_fts(cfg, ds)
    # text output takes two lines per hit: fetch enough hits to reach the line cap
    limit = args.max_lines if args.json else args.max_lines // 2 + 1
    hits = fts_search(cfg, docs, args.query, limit)
    if args.json:
        print(json.dumps(hits, indent=2))
        return 0
    if not hits:
        print("no matches for %r" % args.query)
        return 0
    room = (max(1, (args.max_lines - 1) // 2)
            if len(hits) * 2 > args.max_lines else len(hits))
    for h in hits[:room]:
        print(h["ref"])
        print("    " + h["snippet"])
    if len(hits) > room:
        print("... more hits cut; add words (e.g. the function name), -d, or "
              "raise --max-lines")
    return 0
