"""docshelf notes: per-family Markdown notes that `show` prints."""
import difflib
import json
import os
import re
import stat
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple

import shelf_backends
import shelf_devdocs
from shelf_core import CLIError, Config, pick_docvol, short_name, warn

NOTES_GENERAL_MAX = 50
NOTES_SECTION_MAX = 100
NOTES_TOTAL_MAX = 2000
_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_TYPED = re.compile(r"^(.*?)\s+\(([^()]+)\)$")  # needs a space and a type
_FAMILY = re.compile(r"^[a-z0-9][a-z0-9._+-]*$", re.I)


def notes_path(cfg: Config, family: str) -> str:
    """<notes dir>/<family>.md; the family must be a plain file name."""
    if not family or not _FAMILY.match(family):
        raise CLIError("invalid docvol name %r" % (family,), 2)
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
    """For display: (path, text or None); bad bytes show as U+FFFD."""
    path = notes_path(cfg, family)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return path, f.read()
    except OSError:
        return path, None


def _read_notes_strict(path) -> Optional[str]:
    """For a write: the text, None only when the file does not exist. Any
    other read problem refuses the write, so no note is lost or altered."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise CLIError("cannot read %s: %s; not written" % (path, e), 2)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise CLIError("%s is not valid UTF-8 (%s); fix it in an editor; not written"
                       % (path, e), 2)


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


HEADINGS_FORMAT = 5  # bump when headings.json changes (3: footers, 4-5: headers)


def docvol_headings(ds) -> Dict[str, List[List[Optional[str]]]]:
    """{page: [[heading, anchor], ...]} for the whole docvol."""
    return headings_index(ds)[0]


def headings_index(ds) -> Tuple[Dict[str, List[List[Optional[str]]]], int]:
    """(docvol_headings, number of pages that could not be read), cached in
    <data dir>/headings.json under ds.stamp() and HEADINGS_FORMAT (rebuilt
    when either changes)."""
    stamp = "%s|headings%d" % (ds.stamp(), HEADINGS_FORMAT)
    cache = os.path.join(ds.data_dir(), "headings.json")
    try:
        with open(cache, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("stamp") == stamp and isinstance(data.get("headings"), dict) \
                and isinstance(data.get("skipped"), int):
            return data["headings"], data["skipped"]
    except (OSError, ValueError, AttributeError):
        pass
    heads: Dict[str, List[List[Optional[str]]]] = {}
    skipped = 0
    for page in ds.pages():
        try:
            blocks = ds.page_blocks(page)
        except (OSError, ValueError, CLIError):
            skipped += 1
            continue
        refs = heading_refs(blocks)
        if refs:
            heads[page] = [list(r) for r in refs]
    try:
        os.makedirs(ds.data_dir(), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=ds.data_dir(), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"stamp": stamp, "headings": heads, "skipped": skipped},
                          f, ensure_ascii=False)
            os.replace(tmp, cache)
        except BaseException:
            shelf_devdocs._discard(tmp)
            raise
    except OSError as e:
        warn("cannot write %s: %s" % (cache, e))
    return heads, skipped


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
        out.append("## General: shown by every show of this docvol")
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


def _sections(lines):
    """[(start, end, heading)] for each `## ` section; end is exclusive."""
    heads = [(i, _HEADING.match(l).group(1)) for i, l in enumerate(lines)
             if _HEADING.match(l)]
    return [(i, heads[k + 1][0] if k + 1 < len(heads) else len(lines), h)
            for k, (i, h) in enumerate(heads)]


def _split(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")


def _join(lines):
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


def _target(lines, heading):
    """(start, end, kept_head): the lines of the section `heading` names, or
    None. kept_head is the number of leading lines of the span that are not
    body (the `## ` line, or a title line before an unheaded General)."""
    secs = _sections(lines)
    for start, end, h in secs:
        if h.lower() == heading.lower():  # as display matches; keep the file's text
            return start, end, 1
    if heading == "General":
        end = secs[0][0] if secs else len(lines)
        keep = 0
        while keep < end and not lines[keep].strip():
            keep += 1
        if keep < end and lines[keep].startswith("# "):
            keep += 1
        if any(l.strip() for l in lines[keep:end]):
            return keep, end, 0
    return None


def _check_heading(heading):
    heading = heading.strip()
    m = _HEADING.match(heading)
    if m:  # "## foo" names the section "foo"
        heading = m.group(1)
    if not heading or "\n" in heading or "\r" in heading:
        raise CLIError("a notes heading must be one non-empty line", 2)
    return heading


def set_section(text: str, heading: str, body: str) -> str:
    """Notes text with section `heading` set to `body` (replaced in place, or
    appended at the end). "General" is the lines before the first heading."""
    heading = _check_heading(heading)
    lines = _split(text)
    body_lines = _split(body.rstrip("\n") + "\n") if body.strip("\n") else []
    hit = _target(lines, heading)
    if hit:
        start, end, head = hit
        trail = 0
        while end - trail > start + head and not lines[end - 1 - trail].strip():
            trail += 1
        keep = lines[start:start + head]
        new = lines[:start] + keep + body_lines + [""] * trail + lines[end:]
        if end == len(lines):
            return _join(new)
        return "\n".join(new) + "\n"
    block = ["## " + heading] + body_lines
    if heading == "General":
        rest = lines
        title = []
        while rest and not rest[0].strip():
            rest = rest[1:]
        if rest and rest[0].startswith("# "):
            title, rest = [rest[0], ""], rest[1:]
            while rest and not rest[0].strip():
                rest = rest[1:]
        return _join(title + block + ([""] + rest if rest else []))
    while lines and not lines[-1].strip():
        lines.pop()
    return _join(lines + ([""] if lines else []) + block)


def delete_section(text: str, heading: str) -> str:
    heading = _check_heading(heading)
    lines = _split(text)
    hit = _target(lines, heading)
    if not hit:
        raise CLIError("no section %r in the notes file" % heading, 5)
    start, end, head = hit
    new = lines[:start] + lines[end:]
    if head == 0 and start > 0 and end < len(lines):
        new = lines[:start] + [""] + lines[end:]  # blank line after the title
    return _join(new) if end == len(lines) else "\n".join(new) + "\n"


def _new_file_mode() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def _write_notes(path, text):
    if os.path.islink(path) and not os.path.exists(path):
        raise CLIError("cannot write %s: it is a symlink to a missing file; "
                       "not written" % path, 2)
    # write beside the real file, so a symlinked notes file stays a symlink
    path = os.path.realpath(path)
    d = os.path.dirname(path)
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = _new_file_mode()
    except OSError as e:
        raise CLIError("cannot read %s: %s; not written" % (path, e), 2)
    try:
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    except OSError as e:
        raise CLIError("cannot write %s: %s (set DOCSHELF_NOTES_DIR to a "
                       "writable folder)" % (path, e), 2)
    try:
        os.chmod(tmp, mode)  # mkstemp makes it 0600; keep the file's mode
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        shelf_devdocs._discard(tmp)
        raise CLIError("cannot write %s: %s" % (path, e), 2)
    except BaseException:
        shelf_devdocs._discard(tmp)
        raise


def _write_request(cfg, args, path, text):
    if args.set is not None and args.delete is not None:
        raise CLIError("--set and --delete cannot be used together", 2)
    if args.set is not None and args.text is None:
        raise CLIError("--set needs --text", 2)
    if args.text is not None and args.set is None:
        raise CLIError("--text only goes with --set", 2)
    if args.set is not None:
        if any(_HEADING.match(l) for l in _split(args.text)):
            raise CLIError("--text must not contain a line starting with '## ' "
                           "(that starts a new section; use one --set each)", 2)
        new = set_section(text or "", args.set, args.text)
    else:
        if text is None:
            raise CLIError("no notes file yet: %s" % path, 5)
        new = delete_section(text, args.delete)
    warns = size_warnings(new)
    if warns:
        raise CLIError("not written; the notes would be too big:\n  "
                       + "\n  ".join(warns), 2)
    out = new
    if text and text.count("\r\n") * 2 > text.count("\n"):
        out = new.replace("\n", "\r\n")  # keep a CRLF file CRLF
    _write_notes(path, out)
    print("wrote " + path)
    return new


def cmd_notes(cfg: Config, args) -> int:
    docvols = shelf_backends.installed_docvols(cfg)
    low = args.docvol.lower()
    family = next((d.family for d in docvols if d.family.lower() == low), None)
    if family is None:
        family = pick_docvol(docvols, args.docvol).family
    path = notes_path(cfg, family)
    writing = args.set is not None or args.delete is not None or args.text is not None
    if args.path and writing:
        raise CLIError("--path only prints the file path; use --set/--delete "
                       "without --path to write", 2)
    if args.path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError as e:
            raise CLIError("cannot create %s: %s (set DOCSHELF_NOTES_DIR to "
                           "a writable folder)" % (os.path.dirname(path), e), 2)
        print(path)
        return 0
    if writing:
        text = _write_request(cfg, args, path, _read_notes_strict(path))
        args.check = True
    else:
        _, text = _read_notes(cfg, family)
    if text is None:
        print("notes file not present: %s" % path)
        return 0
    if not args.check:
        sys.stdout.write(text)
        return 0
    entries = [e for d in docvols if d.family == family for e in d.entries()]
    names = {e.name.lower() for e in entries}
    page_headings = []
    skipped = 0
    for d in docvols:
        if d.family == family:
            heads, bad = headings_index(d)
            skipped += bad
            for page, rows in heads.items():
                page_headings += [(h, d.make_ref(page, a)) for h, a in rows]
    warns = check_notes(text, names, {h for h, _r in page_headings})
    print("notes file present: %s" % path)
    for line in notes_matches(text, entries, page_headings):
        print(line)
    if skipped:
        print("note: %d page%s could not be read; %s headings are not checked"
              % (skipped, "" if skipped == 1 else "s",
                 "its" if skipped == 1 else "their"))
    for w in warns:
        print("warning: " + w)
    if not warns:
        print("ok")
    return 1 if warns and not writing else 0
