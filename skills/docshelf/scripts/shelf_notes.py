"""docshelf notes: per-family Markdown notes that `show` prints."""
import difflib
import os
import re
import sys
from typing import List

import shelf_devdocs
from shelf_core import CLIError, Config, pick_docset, short_name

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


def notes_for(cfg, ds, entry_name, entry_type) -> List[str]:
    path, text = _read_notes(cfg, ds.family)
    if text is None:
        return []
    general, sections = parse_notes(text)
    body = []
    if any(l.strip() for l in general):
        body += ["## General"] + general
    want = entry_name.lower()
    wants = {want, short_name(entry_name)}
    for key, items in sections.items():
        for typ, lines in items:
            named = key in wants and (typ is None or typ.lower() == (entry_type or "").lower())
            hit = named or (typ is not None and "%s (%s)" % (key, typ.lower()) == want)
            if hit and any(l.strip() for l in lines):
                body += ["## %s%s" % (entry_name, " (%s)" % typ if named and typ else "")] \
                    + lines
    if not body:
        return []
    return ["--- notes (%s) ---" % path] + body


def general_notes(cfg, ds) -> List[str]:
    path, text = _read_notes(cfg, ds.family)
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
    shorts = {short_name(n) for n in entry_names}
    for name, items in sections.items():
        for typ, _lines in items:
            full = "%s (%s)" % (name, typ.lower()) if typ else name
            if name not in entry_names and name not in shorts and full not in entry_names:
                close = difflib.get_close_matches(name, sorted(entry_names | shorts), 1, 0.6)
                warns.append("section %r matches no entry in the docset; a heading is an "
                             "entry name as search prints it, or its part before '('%s"
                             % (full, "; did you mean %r?" % close[0] if close else ""))
    return warns


def notes_matches(text, entries) -> List[str]:
    """One line per notes section: which `show` prints it (up to 3 REFs)."""
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
    warns = check_notes(text, names)
    print("notes file present: %s" % path)
    for line in notes_matches(text, entries):
        print(line)
    for w in warns:
        print("warning: " + w)
    if not warns:
        print("ok")
    return 1 if warns else 0
