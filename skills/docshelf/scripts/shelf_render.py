"""HTML -> text blocks for docshelf: headings as '#' lines, <pre> fenced,
list items as '- ', tables as ' | ' rows. Pure functions, stdlib only."""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

from shelf_core import cap_lines


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
# "headerlink" (Sphinx) and "copiable-link" (GNU Texinfo) are pilcrow links.
SKIP_CLASSES = {"related", "mobile-nav", "sphinxsidebar", "sphinxsidebarwrapper",
                "breadcrumbs", "breadcrumb", "wy-nav-side", "rst-versions",
                "headerlink", "copiable-link", "toc-drawer", "sidebar-drawer",
                "skip-link"}


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "source", "track", "wbr"}
NO_REF_PREFIXES = ("#", "http://", "https://", "mailto:", "javascript:")


STRUCTURE_TAGS = {"html", "body", "main", "article"}


def _skippable(tag, a) -> bool:
    if tag in SKIP_TAGS:
        return True
    if tag in STRUCTURE_TAGS:  # page structure is never chrome
        return False
    return ("hidden" in a or a.get("role") in SKIP_ROLES
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
    def __init__(self, link=None):
        super().__init__(convert_charrefs=True)
        self.link = link
        self.refs: List[Optional[str]] = []  # one per open <a>: its REF or None
        self.lang = ""  # data-language of the open <pre>
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
        self.cell = None  # (buf index, colspan) of the open table cell

    def _top(self):
        return self.stack[-1] if self.stack else ""

    def flush(self):
        self._end_cell()
        raw = "".join(self.buf)
        self.buf = []
        if self.in_pre:
            text = raw.strip("\n").rstrip()
            text = "```%s\n%s\n```" % (self.lang, text) if text.strip() else ""
            self.lang = ""
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
            if tag not in VOID_TAGS:  # a void tag has no end tag to resume at
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
                self.lang = a.get("data-language") or ""
        elif tag in ("td", "th") and not self.in_pre:
            self._end_cell()
            if self.buf:
                self.buf.append(" | ")
            try:
                span = int(a.get("colspan") or 1)
            except ValueError:
                span = 1
            self.cell = (len(self.buf), span)
        elif tag == "a":
            href = (a.get("href") or "").strip()
            ref = None
            if (self.link and href and not self.in_pre and not self.level
                    and not href.lower().startswith(NO_REF_PREFIXES)):
                ref = self.link(href) or None
            self.refs.append(ref)
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

    def _end_cell(self):
        """Label a non-empty cell spanning several columns: 'Rm (5 cols)'."""
        if self.cell:
            start, span = self.cell
            self.cell = None
            if span > 1 and "".join(self.buf[start:]).strip():
                self.buf.append(" (%d cols)" % span)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip_tag:
                self.skip -= 1
            return
        if tag in ("td", "th"):
            self._end_cell()
        if tag == "a" and self.refs:
            ref = self.refs.pop()
            if ref:
                self.buf.append(" [%s]" % ref)
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


def html_to_text(html: str,
                 link: Optional[Callable[[str], Optional[str]]] = None) -> List[Block]:
    """Page HTML -> blocks (headings as '#' lines, <pre> fenced, items as '- ').
    link(href) may return a REF to append as ' [REF]' after the link text;
    it is not called for #, http(s), mailto and javascript hrefs."""
    p = _TextParser(link)
    p.feed(html)
    p.close()
    return p.blocks


DEFINITION_MAX_LINES = 40  # show --grep adds a matching term's definition up to this


def definition_ends(blocks: List[Block], offset=0) -> dict:
    """{line index of a definition term (<dt>): index after the last line of
    its definition}: the blocks up to the next term at its level or the end
    of its list. Line indexes count from `offset`."""
    starts, n = [], offset
    for b in blocks:
        starts.append(n)
        n += b.text.count("\n") + 1
    starts.append(n)
    ends = {}
    for i, b in enumerate(blocks):
        if b.tag != "dt" or b.level:
            continue
        j = i + 1
        while j < len(blocks) and not blocks[j].level and blocks[j].depth >= b.depth \
                and not (blocks[j].tag == "dt" and blocks[j].depth <= b.depth):
            j += 1
        if j > i + 1:
            for ln in range(starts[i], starts[i + 1]):
                ends[ln] = starts[j]
    return ends


def _section_slice(blocks: List[Block], anchor: Optional[str]) -> Optional[Tuple[int, int]]:
    """(start, end) block indexes of the section the anchor names; None if
    there is no anchor or it isn't found."""
    if not anchor:
        return None
    want = {anchor, unquote(anchor)}
    start = None
    for i, b in enumerate(blocks):
        if any(x in want or unquote(x) in want for x in b.ids):
            start = i
            break
    if start is None:
        return None
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
    return start, end


def section_lines(blocks: List[Block], anchor: Optional[str]) -> Tuple[List[str], dict]:
    """(lines of the section the anchor names, definition_ends for them);
    the whole page if there is no anchor or it isn't found."""
    def lines_of(bs):
        return [ln for b in bs for ln in b.text.split("\n")]

    span = _section_slice(blocks, anchor)
    if span is None:
        if not anchor:
            return lines_of(blocks), definition_ends(blocks)
        return (["note: anchor not found (%s); showing the whole page" % anchor]
                + lines_of(blocks), definition_ends(blocks, 1))
    start, end = span
    return lines_of(blocks[start:end]), definition_ends(blocks[start:end])


def section_headings(blocks: List[Block], anchor: Optional[str]) -> List[str]:
    """Texts (without the #s) of the headings in the section section_lines
    shows for this anchor, the section's own heading included."""
    span = _section_slice(blocks, anchor) or (0, len(blocks))
    return [b.text.lstrip("#").strip() for b in blocks[span[0]:span[1]] if b.level]


def _is_table_row(line) -> bool:
    """Table rows render as cells joined by ' | '."""
    return " | " in line or line.lstrip().startswith("|")


def grep_lines(lines, patterns, def_ends=None) -> List[str]:
    """Lines containing any pattern (case-insensitive), plus the nearest
    heading above each, for a table row its table's first row (the header),
    and for a definition term its definition when def_ends (see
    definition_ends) gives one of at most DEFINITION_MAX_LINES lines. Runs of
    skipped lines become '...'."""
    pats = [p.lower() for p in patterns]
    keep = set()
    for i, line in enumerate(lines):
        if not any(p in line.lower() for p in pats):
            continue
        keep.add(i)
        end = (def_ends or {}).get(i)
        if end is not None and end - i - 1 <= DEFINITION_MAX_LINES:
            keep.update(range(i + 1, end))
        head = next((j for j in range(i - 1, -1, -1) if lines[j].startswith("#")), None)
        if head is not None:
            keep.add(head)
        if _is_table_row(line):
            j = i
            while j > 0 and _is_table_row(lines[j - 1]):
                j -= 1
            keep.add(j)
    out, prev = [], -1
    for i in sorted(keep):
        if i != prev + 1:
            out.append("...")
        out.append(lines[i])
        prev = i
    if keep and prev != len(lines) - 1:
        out.append("...")
    return out


def page_title(blocks) -> Optional[str]:
    """The page's top heading (first h1, else first heading), without #s."""
    heads = [b for b in blocks if b.level]
    if not heads:
        return None
    top = min(b.level for b in heads)
    return next(b.text for b in heads if b.level == top).lstrip("#").strip() or None


def _print_page_title(blocks, lines):
    """'(page: Title)' when the section's heading isn't the page's own, so a
    generic heading like '## Parameters' says what it belongs to."""
    title = page_title(blocks)
    if title and lines and lines[0].startswith("#") \
            and lines[0].lstrip("#").strip() != title:
        print("(page: %s)" % title)


def _print_lines(lines, args, def_ends=None):
    footer = None
    if getattr(args, "grep", None):
        total = len(lines)
        wanted = " or ".join(repr(g) for g in args.grep)
        hits = [i for i, l in enumerate(lines)
                if any(g.lower() in l.lower() for g in args.grep)]
        matched = len(hits)
        with_def = any((def_ends or {}).get(i, i + 1) - i - 1 in
                       range(1, DEFINITION_MAX_LINES + 1) for i in hits)
        lines = grep_lines(lines, args.grep, def_ends)
        if not lines:
            print("no lines match %s in this section (%d lines); drop --grep to "
                  "see it" % (wanted, total))
            return
        footer = ("(all %d lines containing %s are shown; the section has %d lines)"
                  % (matched, wanted, total))
        if with_def:
            footer = footer[:-1] + "; a matching term is shown with its definition)"
    if not args.full:
        lines = cap_lines(lines, args.max_lines,
                          "raise --max-lines or use --full for the whole section")
    for line in lines:
        print(line)
    if footer:
        print(footer)

