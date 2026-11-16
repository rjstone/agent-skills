"""docshelf lookup commands: search."""
import argparse
import json
import re
import sys
from urllib.parse import unquote
from typing import Dict, List, Optional, Tuple

import shelf_devdocs
import shelf_notes
from shelf_render import (_print_lines, _print_page_title, html_to_text,
                          section_lines)
from shelf_core import (CLIError, Config, cap_lines, pick_docset, rank,
                        select_docsets, short_name)

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
    twin = {}  # (docset, page, short name) -> ref of first anchored hit
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


def cmd_search(cfg: Config, args: argparse.Namespace) -> int:
    _join_query(args)
    if not args.query:
        raise CLIError("empty search query", 2)
    docs = select_docsets(cfg, shelf_devdocs.installed_docsets(cfg),
                          args.docset or [], args.all)
    words = args.query.lower().split()
    want_type = args.type.lower() if args.type else None
    hits = []
    no_anchor = set()  # refs of entries that point at a whole page
    page_of: Dict[str, str] = {}  # ref -> page
    q_lower = args.query.lower()
    for ds in docs:
        for e in ds.entries():
            if want_type is not None and e.type.lower() != want_type:
                continue
            name = e.name
            r = rank(args.query, name)
            # several words: a name holding all of them in any order ranks
            # like a substring hit (2)
            if (r is None or r == 3) and len(words) > 1 \
                    and all(w in name.lower() for w in words):
                r = 2
            if r is None:
                continue
            if r and short_name(name) == q_lower:
                r = 0  # 'f(a, b)' for query 'f' is an exact match
            page_of[e.ref] = e.page
            if e.anchor is None:
                no_anchor.add(e.ref)
            hits.append((r, len(name), name, ds.name, e.ref, e.type))
    # within a rank, entries with an anchor (a section) before whole pages
    hits.sort(key=lambda h: (h[0], h[4] in no_anchor) + h[1:5])
    hits, also = _fold_bare_entries(hits, no_anchor, page_of)
    hint = "raise --max-lines or narrow the query, -d or --type"
    if args.json:
        items = []
        for r, _l, n, d, ref, t in hits[:args.max_lines]:
            item = {"ref": ref, "docset": d, "type": t, "name": n, "rank": r}
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
            lines.append("no matches for %r (entry names only; fts searches the "
                         "text inside pages)" % args.query)
    for line in cap_lines(lines, args.max_lines, hint):
        print(line)
    return 0


def _split_ref(ref):
    name, sep, rest = ref.partition(":")
    if not sep or not name or not rest:
        raise CLIError("bad reference %r (expected <docset>:<path>[#anchor])"
                       % ref, 2)
    return name, rest


def resolve_doc_path(page, href):
    """href resolved against the page's folder: '..' pops, a leading '/' is
    the docset root; returns (path, fragment or None)."""
    rel, _, frag = href.partition("#")
    segments = [] if rel.startswith("/") else page.split("/")[:-1]
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if segments:
                segments.pop()
        else:
            segments.append(part)
    return "/".join(segments), frag or None


def cmd_show(cfg: Config, args: argparse.Namespace) -> int:
    name, rest = _split_ref(args.ref)
    ds = pick_docset(shelf_devdocs.installed_docsets(cfg), name)
    page, anchor, entry = ds.resolve(rest)
    known = set(ds.pages())

    def link(href):
        target, frag = resolve_doc_path(page, href)
        return ds.make_ref(target, frag) if target in known else None

    blocks = html_to_text(ds.page_html(page), link=link)
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
        if entry is not None:
            out = shelf_notes.notes_for(cfg, ds, entry.name, entry.type)
        else:
            out = shelf_notes.general_notes(cfg, ds)
        for line in out:
            print(line)
        _p, text = shelf_notes._read_notes(cfg, ds.family)
        for w in shelf_notes.size_warnings(text or ""):
            print("warning: notes: " + w, file=sys.stderr)
    return 0
