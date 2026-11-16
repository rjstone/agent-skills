"""docshelf notes: per-family Markdown notes that `show` prints."""
import difflib
import json
import os
import re
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple

import shelf_devdocs
from shelf_core import CLIError, Config, pick_docset, short_name
from shelf_render import html_to_text

NOTES_GENERAL_MAX = 50
NOTES_SECTION_MAX = 100
NOTES_TOTAL_MAX = 2000
_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_TYPED = re.compile(r"^(.*?)\s+\(([^()]+)\)$")  # needs a space and a type
_FAMILY = re.compile(r"^[a-z0-9][a-z0-9._+-]*$", re.I)


def notes_path(cfg: Config, family: str) -> str:
    """<notes dir>/<family>.md; the family must be a plain file name."""
    if not family or not _FAMILY.match(family):
        raise CLIError("invalid docset name %r" % (family,), 2)
    return os.path.join(cfg.notes_dir, family + ".md")


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


def _read_notes(cfg, family):
    path = notes_path(cfg, family)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return path, f.read()
    except OSError:
        return path, None


def _entry_hit(key, typ, name, entry_type):
    """Does the notes section (key, typ) name this entry or heading?"""
    want = name.lower()
    named = key in (want, short_name(name)) and (
        typ is None or typ.lower() == (entry_type or "").lower())
    return named, named or (typ is not None and "%s (%s)" % (key, typ.lower()) == want)


def _notes_body(cfg, ds, entry_name, entry_type, headings) -> List[str]:
    path, text = _read_notes(cfg, ds.family)
    if text is None:
        return []
    general, sections = parse_notes(text)
    body = []
    if any(l.strip() for l in general):
        body += ["## General"] + general
    printed = set()  # ids of the line lists already shown
    if entry_name is not None:
        for key, items in sections.items():
            for typ, lines in items:
                named, hit = _entry_hit(key, typ, entry_name, entry_type)
                if hit and any(l.strip() for l in lines):
                    printed.add(id(lines))
                    body += ["## %s%s" % (entry_name, " (%s)" % typ if named and typ else "")] \
                        + lines
    for heading in headings:  # headings inside the section being shown
        for key, items in sections.items():
            for typ, lines in items:
                if id(lines) in printed or not any(l.strip() for l in lines):
                    continue
                if _entry_hit(key, typ, heading, None)[1]:
                    printed.add(id(lines))
                    body += ["## " + heading] + lines
    if not body:
        return []
    return ["--- notes (%s) ---" % path] + body


def notes_for(cfg, ds, entry_name, entry_type, headings: Iterable[str] = ()) -> List[str]:
    """General notes, the entry's section, then the sections whose heading
    matches a heading in `headings` (those inside the section shown)."""
    return _notes_body(cfg, ds, entry_name, entry_type, list(headings))


def general_notes(cfg, ds, headings: Iterable[str] = ()) -> List[str]:
    return _notes_body(cfg, ds, None, None, list(headings))


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


def check_notes(text, entry_names, heading_names=()) -> List[str]:
    """heading_names: names of headings inside pages (as in the page)."""
    warns = size_warnings(text)
    _, sections = parse_notes(text)
    shorts = {short_name(n) for n in entry_names}
    heads = {h.lower() for h in heading_names} | {short_name(h) for h in heading_names}
    for name, items in sections.items():
        for typ, _lines in items:
            full = "%s (%s)" % (name, typ.lower()) if typ else name
            if name not in entry_names and name not in shorts and full not in entry_names \
                    and name not in heads and full not in heads:
                close = difflib.get_close_matches(
                    name, sorted(entry_names | shorts | heads), 1, 0.6)
                warns.append("section %r matches no entry or page heading; a heading is an "
                             "entry name as search prints it, its part before '(', or a "
                             "heading inside a page%s"
                             % (full, "; did you mean %r?" % close[0] if close else ""))
    return warns


# --- headings inside pages ---------------------------------------------------

def heading_refs(blocks) -> List[Tuple[str, Optional[str]]]:
    """(heading text without #s, anchor `show` uses for it) for each heading:
    its own first id, else the nearest enclosing heading's anchor."""
    out, stack = [], []  # stack: (level, anchor)
    for b in blocks:
        if not b.level:
            continue
        while stack and stack[-1][0] >= b.level:
            stack.pop()
        anchor = b.ids[0] if b.ids else (stack[-1][1] if stack else None)
        stack.append((b.level, anchor))
        out.append((b.text.lstrip("#").strip(), anchor))
    return out


def docset_headings(ds) -> Dict[str, List[List[Optional[str]]]]:
    """{page: [[heading, anchor], ...]} for the whole docset, cached in
    <data dir>/headings.json under ds.stamp() (rebuilt when it changes)."""
    stamp = ds.stamp()
    cache = os.path.join(ds.data_dir(), "headings.json")
    try:
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("stamp") == stamp and isinstance(data.get("headings"), dict):
            return data["headings"]
    except (OSError, ValueError, AttributeError):
        pass
    heads: Dict[str, List[List[Optional[str]]]] = {}
    for page in ds.pages():
        try:
            blocks = html_to_text(ds.page_html(page))
        except (OSError, ValueError, CLIError):
            continue
        refs = heading_refs(blocks)
        if refs:
            heads[page] = [list(r) for r in refs]
    try:
        os.makedirs(ds.data_dir(), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=ds.data_dir(), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"stamp": stamp, "headings": heads}, f, ensure_ascii=False)
            os.replace(tmp, cache)
        except BaseException:
            shelf_devdocs._discard(tmp)
            raise
    except OSError as e:
        shelf_devdocs._warn("cannot write %s: %s" % (cache, e))
    return heads


def notes_matches(text, entries, page_headings=()) -> List[str]:
    """One line per notes section: which `show` prints it (up to 3 REFs).
    page_headings: (heading text, REF) pairs for headings inside pages."""
    general, sections = parse_notes(text)
    written = {}  # lowercased heading -> heading as written
    for line in text.splitlines():
        if line.startswith("## "):
            written.setdefault(line[3:].strip().lower(), line[3:].strip())
    out = []
    if any(l.strip() for l in general):
        out.append("## General: shown by every show of this docset")
    for key, items in sections.items():
        for typ, _lines in items:
            refs = []
            for e in entries:
                n, t = e.name, e.type
                low = n.lower()
                named = key in (low, short_name(n)) and (
                    typ is None or typ.lower() == (t or "").lower())
                if named or (typ is not None and "%s (%s)" % (key, typ.lower()) == low):
                    refs.append(e.ref)
            for h, ref in page_headings:
                if ref not in refs and _entry_hit(key, typ, h, None)[1]:
                    refs.append(ref)
            if refs:
                label = "%s%s" % (key, " (%s)" % typ if typ else "")
                label = written.get(label.lower(), label)
                more = " (+%d more)" % (len(refs) - 3) if len(refs) > 3 else ""
                out.append("## %s: shown by show %s%s" % (label, ", ".join(refs[:3]), more))
    return out


def cmd_notes(cfg: Config, args) -> int:
    docsets = shelf_devdocs.installed_docsets(cfg)
    low = args.docset.lower()
    family = next((d.family for d in docsets if d.family.lower() == low), None)
    if family is None:
        family = pick_docset(docsets, args.docset).family
    path = notes_path(cfg, family)
    if args.path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError as e:
            raise CLIError("cannot create %s: %s (set DOCSHELF_NOTES_DIR to "
                           "a writable folder)" % (os.path.dirname(path), e), 2)
        print(path)
        return 0
    _, text = _read_notes(cfg, family)
    if text is None:
        print("notes file not present: %s" % path)
        return 0
    if not args.check:
        sys.stdout.write(text)
        return 0
    entries = [e for d in docsets if d.family == family for e in d.entries()]
    names = {e.name.lower() for e in entries}
    page_headings = []
    for d in docsets:
        if d.family == family:
            for page, rows in docset_headings(d).items():
                page_headings += [(h, d.make_ref(page, a)) for h, a in rows]
    warns = check_notes(text, names, {h for h, _r in page_headings})
    print("notes file present: %s" % path)
    for line in notes_matches(text, entries, page_headings):
        print(line)
    for w in warns:
        print("warning: " + w)
    if not warns:
        print("ok")
    return 1 if warns else 0
