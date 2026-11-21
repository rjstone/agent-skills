"""Stdlib Markdown/MDX to HTML for llms.txt sites. A small line-based block
parser plus an inline pass; the result goes through build_html's tokenizer and
serializer, which drop script/style/form/iframe and turn images into alt text.
"""
import html as htmllib
import re
from typing import Dict, List, Optional, Set, Tuple

from build_html import _serialize, _tokens

# ---- front matter ------------------------------------------------------


def front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """(title/description found in a leading --- block, the body without it)."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            meta: Dict[str, str] = {}
            for ln in lines[1:end]:
                m = re.match(r"^(title|description)\s*:\s*(.*?)\s*$", ln)
                if m:
                    v = m.group(2)
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    meta[m.group(1)] = v
            return meta, "\n".join(lines[end + 1:])
    return {}, text


def slugify(text: str) -> str:
    """GitHub-style heading id: lowercase, keep letters, digits, - _ and
    spaces, spaces become hyphens."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _unique(slug: str, seen: Set[str]) -> str:
    cand, n = slug, 0
    while cand in seen:
        n += 1
        cand = "%s-%d" % (slug, n)
    seen.add(cand)
    return cand


# ---- MDX pre-pass ------------------------------------------------------

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TAG = re.compile(r"</?[A-Z][\w.]*")
_ATTR = re.compile(r"""(\w+)=(?:"([^"]*)"|'([^']*)'|\{([^}]*)\})""")
_IMPORT = re.compile(r"""^import\s+(?:[\w*{},\s]+\s+from\s+)?['"]|"""
                     r"""^export\s+(?:const|let|var|default|function|\{|\*)""")


def _tag_end(text: str, start: int) -> Optional[int]:
    """Index just past the `>` closing the tag at `start` (quotes and {} aware)."""
    quote, depth = "", 0
    for i in range(start, len(text)):
        c = text[i]
        if quote:
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth <= 0:
            return i + 1
    return None


def _dedent(lines: List[str], start: int) -> None:
    body = [ln for ln in lines[start:] if ln.strip()]
    cut = min((len(ln) - len(ln.lstrip(" ")) for ln in body), default=0)
    if cut:
        lines[start:] = [ln[cut:] if ln.strip() else "" for ln in lines[start:]]


def _in_code(line: str, pos: int) -> bool:
    return line[:pos].count("`") % 2 == 1


def _mdx(lines: List[str]) -> List[str]:
    """Drop imports/exports/comments; replace component tags by their title
    or link text; dedent component bodies. Fenced code is left alone."""
    out: List[str] = []
    stack: List[Tuple[str, int]] = []
    fence = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = ""
            out.append(line)
            i += 1
            continue
        if m:
            fence = m.group(1)
            out.append(line)
            i += 1
            continue
        line = re.sub(r"^\t+", lambda t: "    " * len(t.group(0)), line)
        if _IMPORT.match(line):
            depth = line.count("{") - line.count("}")
            i += 1
            while depth > 0 and i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue
        if re.match(r"^\s*\{/\*.*\*/\}\s*$", line):
            i += 1
            continue
        tag = next((t for t in _TAG.finditer(line) if not _in_code(line, t.start())), None)
        if tag is None:
            out.append(line)
            i += 1
            continue
        text, j = line, i
        end = _tag_end(text, tag.start())
        while end is None and j + 1 < len(lines):
            j += 1
            text += "\n" + lines[j]
            end = _tag_end(text, tag.start())
        if end is None:
            end = len(text)
        raw = text[tag.start():end]
        before, after = text[:tag.start()], text[end:]
        name = tag.group(0).lstrip("</")
        closing = tag.group(0).startswith("</")
        selfclose = raw.rstrip(">").rstrip().endswith("/")
        alone = not before.strip() and not after.strip()
        if closing:
            names = [s[0] for s in stack]
            if name in names:
                idx = len(names) - 1 - names[::-1].index(name)
                for _, start in reversed(stack[idx:]):
                    _dedent(out, start)
                del stack[idx:]
        if alone:
            if closing:
                out.append("")
            else:
                attrs = {k: v1 or v2 or v3 for k, v1, v2, v3 in _ATTR.findall(raw)}
                out.append("")
                if attrs.get("title") and attrs.get("href"):
                    out.append("[%s](%s)" % (attrs["title"], attrs["href"]))
                elif attrs.get("title"):
                    out.append("**%s**" % attrs["title"])
                out.append("")
                if not selfclose:
                    stack.append((name, len(out)))
            i = j + 1
        else:
            if not closing and not selfclose:
                stack.append((name, len(out)))
            lines[j] = before + after
            i = j
    for _, start in reversed(stack):
        _dedent(out, start)
    return out


# ---- inline ------------------------------------------------------------

_ESC = htmllib.escape


def _esc(s: str) -> str:
    return _ESC(s, quote=False)


def _attr_val(s: str) -> str:
    return s.replace('"', "&quot;")


_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\(\s*([^\s()]*(?:\([^\s()]*\)[^\s()]*)*)"
                   r"""(?:\s+(?:"([^"]*)"|'([^']*)'))?\s*\)""")
_IMG = re.compile(r"""!\[([^\]]*)\]\(\s*[^)\s]*(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)""")


def _inline(text: str) -> str:
    stash: List[str] = []

    def keep(s: str) -> str:
        stash.append(s)
        return "\x00%d\x00" % (len(stash) - 1)

    def code(m):
        c = m.group(2).replace("\n", " ")
        if len(c) > 2 and c[0] == c[-1] == " " and c.strip():
            c = c[1:-1]
        return keep("<code>%s</code>" % _esc(c))

    text = re.sub(r"(?<!\\)(`+)(?!`)(.+?)(?<!`)\1(?!`)", code, text, flags=re.S)
    text = re.sub(r"<((?:https?|ftp)://[^\s<>]+)>",
                  lambda m: keep('<a href="%s">%s</a>' % (_attr_val(_esc(m.group(1))),
                                                          _esc(m.group(1)))), text)
    text = re.sub(r"<([\w.+-]+@[\w-]+\.[\w.-]+)>",
                  lambda m: keep('<a href="mailto:%s">%s</a>' % (m.group(1), m.group(1))), text)
    text = re.sub(r"<(?:/?[a-z][\w-]*(?:\s[^<>]*)?/?|!--.*?--)>",
                  lambda m: keep(m.group(0)), text, flags=re.S)
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>~])", lambda m: keep(_esc(m.group(1))), text)
    text = _esc(text)
    text = _IMG.sub(lambda m: m.group(1), text)

    def link(m):
        url = m.group(2)
        if url.startswith("&lt;") and url.endswith("&gt;"):
            url = url[4:-4]
        title = m.group(3) if m.group(3) is not None else m.group(4)
        attrs = ' href="%s"' % _attr_val(url)
        if title is not None:
            attrs += ' title="%s"' % _attr_val(title)
        return keep("<a%s>" % attrs) + m.group(1) + keep("</a>")

    text = _LINK.sub(link, text)
    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"(?<![\w])__(?=\S)(.+?)(?<=\S)__(?![\w])", r"<strong>\1</strong>",
                  text, flags=re.S)
    text = re.sub(r"(?<!\*)\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)", r"<em>\1</em>", text, flags=re.S)
    text = re.sub(r"(?<![\w])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w])", r"<em>\1</em>",
                  text, flags=re.S)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", text, flags=re.S)
    text = re.sub(r"(?: {2,}|\\)\n", lambda m: keep("<br>"), text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


# ---- blocks ------------------------------------------------------------

_LIST = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)(.*)$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_BLOCK_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_DELIM = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_HTML_BLOCK = re.compile(
    r"^ {0,3}(?:<!--|</?(?:details|summary|div|p|table|thead|tbody|tr|td|th|ul|ol|li|pre|"
    r"blockquote|section|figure|figcaption|center|dl|dt|dd|hr|h[1-6]|iframe|script|style|"
    r"form|nav|aside|header|footer|main|article|video)\b)", re.I)


def _indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def _starts_block(ln: str) -> bool:
    """True when `ln` begins a block that may interrupt a paragraph."""
    if _BLOCK_FENCE.match(ln) or _ATX.match(ln) or _HR.match(ln) or _HTML_BLOCK.match(ln):
        return True
    if re.match(r"^ {0,3}>", ln):
        return True
    m = _LIST.match(ln)
    return bool(m and m.group(4).strip() and (not m.group(2)[0].isdigit()
                                              or m.group(2)[:-1] == "1"))


def _is_table(lines: List[str], i: int) -> bool:
    return (i + 1 < len(lines) and "|" in lines[i] and "|" in lines[i + 1]
            and bool(_DELIM.match(lines[i + 1])))


def _cells(row: str) -> List[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]


def _heading(level: int, text: str, seen: Set[str]) -> str:
    slug = slugify(re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", ""))
    ident = ' id="%s"' % _unique(slug, seen) if slug else ""
    return "<h%d%s>%s</h%d>" % (level, ident, _inline(text), level)


def _list(lines: List[str], i: int, seen: Set[str]) -> Tuple[str, int]:
    first = _LIST.match(lines[i])
    ind, ordered = len(first.group(1)), first.group(2)[0].isdigit()
    start = int(first.group(2)[:-1]) if ordered else 1
    items: List[List[str]] = []
    loose, n = False, len(lines)
    while i < n:
        m = _LIST.match(lines[i])
        if not m or len(m.group(1)) != ind or m.group(2)[0].isdigit() != ordered:
            break
        off = ind + len(m.group(2)) + (min(len(m.group(3)), 4) or 1)
        item = [m.group(4)]
        i += 1
        while i < n:
            ln = lines[i]
            if not ln.strip():
                j = i
                while j < n and not lines[j].strip():
                    j += 1
                if j >= n:
                    i = j
                    break
                nxt = lines[j]
                nm = _LIST.match(nxt)
                if _indent(nxt) > ind:
                    if not nm or not any(_LIST.match(x) for x in item[1:]):
                        loose = True
                    item.extend([""] * (j - i))
                    i = j
                    continue
                if nm and _indent(nxt) == ind and nm.group(2)[0].isdigit() == ordered:
                    loose = True
                i = j
                break
            if _indent(ln) > ind:
                item.append(ln[min(_indent(ln), off):])
                i += 1
            elif _LIST.match(ln) and _indent(ln) == ind:
                break
            elif item[-1].strip() and not _starts_block(ln):
                item.append(ln.strip())
                i += 1
            else:
                break
        items.append(item)
    body = "\n".join("<li>%s</li>" % _blocks(it, seen, not loose) for it in items)
    tag = "ol" if ordered else "ul"
    attr = ' start="%d"' % start if ordered and start != 1 else ""
    return "<%s%s>\n%s\n</%s>" % (tag, attr, body, tag), i


def _blocks(lines: List[str], seen: Set[str], tight: bool = False) -> str:
    out: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        m = _BLOCK_FENCE.match(ln)
        if m:
            ind, marker, lang = len(m.group(1)), m.group(2), m.group(3)
            body: List[str] = []
            i += 1
            while i < n:
                s = lines[i].strip()
                if s.startswith(marker[0] * len(marker)) and not s.strip(marker[0]):
                    i += 1
                    break
                body.append(lines[i][min(ind, _indent(lines[i])):])
                i += 1
            cls = ' class="language-%s"' % _attr_val(_esc(lang)) if lang else ""
            out.append("<pre><code%s>%s</code></pre>" % (cls, _esc("\n".join(body))))
            continue
        if ln.startswith("    "):
            body = []
            while i < n and (lines[i].startswith("    ") or not lines[i].strip()):
                body.append(lines[i][4:])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            out.append("<pre><code>%s</code></pre>" % _esc("\n".join(body)))
            continue
        m = _ATX.match(ln)
        if m:
            out.append(_heading(len(m.group(1)), m.group(2) or "", seen))
            i += 1
            continue
        if _HR.match(ln):
            out.append("<hr>")
            i += 1
            continue
        if re.match(r"^ {0,3}>", ln):
            inner: List[str] = []
            while i < n and re.match(r"^ {0,3}>", lines[i]):
                inner.append(re.sub(r"^ {0,3}> ?", "", lines[i]))
                i += 1
            out.append("<blockquote>\n%s\n</blockquote>" % _blocks(inner, seen))
            continue
        if _LIST.match(ln):
            html, i = _list(lines, i, seen)
            out.append(html)
            continue
        if _is_table(lines, i):
            head = _cells(ln)
            rows: List[List[str]] = []
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append((_cells(lines[i]) + [""] * len(head))[:len(head)])
                i += 1
            th = "".join("<th>%s</th>" % _inline(c) for c in head)
            tb = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c) for c in r)
                         for r in rows)
            out.append("<table><thead><tr>%s</tr></thead>%s</table>"
                       % (th, "<tbody>%s</tbody>" % tb if rows else ""))
            continue
        if _HTML_BLOCK.match(ln):
            raw = [ln]
            tm = re.match(r"^ {0,3}<(pre|script|style)\b", ln, re.I)
            i += 1
            if tm:
                close = "</%s" % tm.group(1).lower()
                while close not in raw[-1].lower() and i < n:
                    raw.append(lines[i])
                    i += 1
            else:
                while i < n and lines[i].strip():
                    raw.append(lines[i])
                    i += 1
            out.append("\n".join(raw))
            continue
        para = [ln.lstrip()]
        i += 1
        heading = 0
        while i < n and lines[i].strip():
            nxt = lines[i]
            s = _SETEXT.match(nxt)
            if s:
                heading = 1 if s.group(1)[0] == "=" else 2
                i += 1
                break
            if _starts_block(nxt) or _is_table(lines, i):
                break
            para.append(nxt.lstrip())
            i += 1
        text = "\n".join(para)
        if heading:
            out.append(_heading(heading, " ".join(p.strip() for p in para), seen))
        else:
            html = _inline(text.rstrip())
            out.append(html if tight else "<p>%s</p>" % html)
    return ("" if tight else "\n").join(out)


def md_to_html(text: str) -> str:
    """Body HTML for a Markdown/MDX page (front matter dropped)."""
    _, body = front_matter(text)
    body = body.replace("\x00", "")
    html = _blocks(_mdx(body.split("\n")), set())
    return _serialize(_tokens(html))
