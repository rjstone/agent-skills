"""Sphinx Intersphinx inventories (objects.inv, version 2)."""
import re
import zlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

from build_core import CLIError

# Sphinx's line pattern (sphinx.util.inventory), but the role must hold a
# ":" so a number word inside a name is not taken for the priority
_LINE = re.compile(r"(.+?)\s+(\S+:\S+)\s+(-?\d+)\s+?(\S*)\s+(.*)")


@dataclass(frozen=True)
class InvEntry:
    name: str
    role: str        # "domain:role", e.g. "py:function", "std:doc"
    priority: int
    uri: str         # "$" already expanded to the name
    dispname: str    # "-" means "same as name"


def parse_inventory(data: bytes) -> Tuple[dict, List[InvEntry]]:
    """(header {"project", "version"}, entries); CLIError(code 3) when data is
    not a version 2 inventory."""
    lines = data.split(b"\n", 4)
    first = lines[0].decode("utf-8", "replace").strip()
    if first != "# Sphinx inventory version 2":
        what = "version 1" if first == "# Sphinx inventory version 1" else "not an inventory"
        raise CLIError("objects.inv: %s (need a Sphinx inventory version 2)" % what, 3)
    if len(lines) < 5:
        raise CLIError("objects.inv: truncated header", 3)
    header = {}
    for raw, key in ((lines[1], "project"), (lines[2], "version")):
        text = raw.decode("utf-8", "replace")
        prefix = "# %s:" % key.capitalize()
        if not text.startswith(prefix):
            raise CLIError("objects.inv: bad header line %r" % text, 3)
        header[key] = text[len(prefix):].strip()
    try:
        body = zlib.decompress(lines[4]).decode("utf-8")
    except (zlib.error, UnicodeDecodeError) as e:
        raise CLIError("objects.inv: cannot decompress (%s)" % e, 3)
    entries = []
    for line in body.splitlines():
        m = _LINE.match(line.rstrip())
        if not m:
            continue
        name, role, prio, uri, disp = m.groups()
        if ":" not in role:
            continue
        if uri.endswith("$"):
            uri = uri[:-1] + name
        entries.append(InvEntry(name, role, int(prio), uri, disp))
    return header, entries


def split_uri(uri: str) -> Tuple[str, Optional[str]]:
    """("page uri", anchor or None)."""
    page, sep, anchor = uri.partition("#")
    return page, (anchor if sep and anchor else None)


def page_key(page_uri: str) -> str:
    """A docshelf page name: no ".html", no trailing "/", root = "index"."""
    key = page_uri
    if key.endswith(".html"):
        key = key[:-5]
    key = key.rstrip("/")
    return key or "index"
