"""The build plan: which pages are kept in full and which become stubs.

Approach A (the role rule plus overrides and hand edits) writes it; a later
decision-model step can rewrite "keep", "description" and "why" in the same
file without changing the build."""
import fnmatch
import json
import os
import tempfile
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from build_docvol import role_label
from build_doxygen import dropped_page
from build_inventory import InvEntry, page_key, split_uri
from build_llms import Tree

FORMAT = 1
CARRIED = ("signals", "fetched", "fetch_error")
# Doxygen entries that only name a page; a page with nothing else is a stub
DOXYGEN_HEADINGS = frozenset({"doxygen:File", "doxygen:Module", "doxygen:Namespace", "std:doc"})


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _group(key: str) -> str:
    return key.split("/", 1)[0]


def _generated(key: str) -> bool:
    """Sphinx's generated pages (general index, module indexes, search): the
    inventory lists them, the site may not have them, and they hold nothing
    a lookup needs."""
    return key in ("genindex", "search") or ("/" not in key and key.endswith("modindex"))


def _choose(key: str, rule_keep: str, rule_why: str, stored: List[List[str]],
            cli: List[List[str]], prev: Optional[dict]) -> Tuple[str, str]:
    """A page's (keep, why). Lowest to highest: the rule, stored overrides, a
    model choice from the old plan (why starts "model:"; the caller passes
    prev=None to drop it), command-line overrides, then a "manual" old choice."""
    keep, why = rule_keep, rule_why
    for mode, pat in stored:
        if fnmatch.fnmatchcase(key, pat):
            keep, why = mode, "override: " + pat
    if prev and str(prev.get("why", "")).startswith("model:"):
        keep, why = prev["keep"], prev["why"]
    for mode, pat in cli:
        if fnmatch.fnmatchcase(key, pat):
            keep, why = mode, "override: " + pat
    if prev and prev.get("why") == "manual":
        keep, why = prev["keep"], "manual"
    return keep, why


def make_plan(source: str, inv_sha256: str, header: dict, entries: List[InvEntry],
              overrides: List[Tuple[str, str]], old: Optional[dict] = None,
              reset: bool = False, base_url: Optional[str] = None,
              kind: str = "sphinx") -> dict:
    """A plan for entries. With old, its overrides come first (unless reset),
    its base_url is kept unless given, and its "manual" pages keep their
    choice; pages no longer in the inventory are dropped. kind "doxygen"
    swaps the page rule (pages documenting members are full), the titles
    and drops Doxygen's index and listing pages."""
    doxygen = kind == "doxygen"
    stored = [] if (old is None or reset) else [list(o) for o in old.get("overrides", [])]
    cli = [[mode, pat] for mode, pat in overrides]
    all_overrides = stored + cli
    if _is_url(source):
        live = source
    else:
        live = base_url or (old or {}).get("base_url")

    roles: Dict[str, set] = defaultdict(set)
    uris: Dict[str, str] = {}
    titles: Dict[str, str] = {}
    types: Counter = Counter()
    for e in entries:
        page_uri, anchor = split_uri(e.uri)
        if doxygen and dropped_page(page_uri):
            continue
        key = page_key(page_uri)
        roles[key].add(e.role)
        uris.setdefault(key, page_uri)
        if doxygen:
            types[role_label(e.role)] += 1
            if anchor is None and e.role in DOXYGEN_HEADINGS | {"doxygen:Class", "doxygen:Struct"}:
                titles.setdefault(key, e.name)
        elif e.role == "std:doc":
            titles[key] = e.name if e.dispname == "-" else e.dispname

    old_pages = (old or {}).get("pages", {})
    pages = {}
    for key in sorted(roles):
        if _generated(key):
            continue
        if doxygen:
            members = sorted(roles[key] - DOXYGEN_HEADINGS)
            keep, why = ("full", "roles: " + ", ".join(members)) if members \
                else ("stub", "roles: headings only")
        else:
            domain = sorted(r for r in roles[key] if not r.startswith("std:"))
            keep, why = ("full", "roles: " + ", ".join(domain)) if domain \
                else ("stub", "roles: std only")
        prev = old_pages.get(key)
        keep, why = _choose(key, keep, why, stored, cli, prev if not reset or
                            (prev or {}).get("why") == "manual" else None)
        if "/" in key and not doxygen:
            group = _group(key)
            section = titles.get(group + "/index", group)
        else:
            section = None
        pages[key] = {"keep": keep, "title": titles.get(key, key), "section": section,
                      "description": (prev or {}).get("description"), "why": why,
                      "uri": uris[key]}
    plan = {"format": FORMAT, "kind": kind, "source": source, "base_url": live,
            "inventory_sha256": inv_sha256,
            "project": header.get("project", ""), "version": header.get("version", ""),
            "entry_count": len(entries), "rule": "doxygen-members" if doxygen else "roles",
            "overrides": all_overrides, "pages": pages}
    if doxygen:
        plan["doxygen"] = header.get("doxygen", "")
        plan["types"] = dict(types.most_common())
    return plan


def summarize(plan: dict, old: Optional[dict]) -> List[str]:
    """Lines for people: counts, the largest page groups, changes since old,
    and a warning when the role rule kept nothing."""
    pages = plan["pages"]
    full = sum(1 for p in pages.values() if p["keep"] == "full")
    lines = ["%d pages: %d full, %d stub; %d entries"
             % (len(pages), full, len(pages) - full, plan.get("entry_count", 0))]
    groups: Dict[str, Counter] = defaultdict(Counter)
    for key, p in pages.items():
        groups[_group(key)][p["keep"]] += 1
    biggest = sorted(groups, key=lambda g: (-sum(groups[g].values()), g))
    if plan.get("kind") == "doxygen":
        lines.append("index: %s (Doxygen %s)" % (plan.get("index", "?"),
                                                plan.get("doxygen") or "version unknown"))
        lines.append("  " + ", ".join("%s %d" % t for t in plan.get("types", {}).items()))
        biggest = []
    for g in biggest[:5]:
        lines.append("  %s: %d full, %d stub" % (g, groups[g]["full"], groups[g]["stub"]))
    if plan.get("archive"):
        lines.append("archive: %s" % plan["archive"])
    lines.extend(_added_dropped(pages, old))
    if full == 0 and biggest:
        top = next((g for g in biggest if any("/" in k for k in pages if _group(k) == g)),
                   biggest[0])
        lines.append("warning: no page has a domain role (every entry is std:*), so the "
                     "rule keeps nothing in full; for prose reference use --full '%s/*' "
                     "(or another group above)" % top)
    return lines


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def make_llms_plan(source: str, tree: Tree, overrides: List[Tuple[str, str]],
                   old: Optional[dict] = None, reset: bool = False) -> dict:
    """A plan for an llms.txt tree: every page full, then the precedence of
    _choose. Pages still listed keep the old plan's CARRIED fields."""
    stored = [] if (old is None or reset) else [list(o) for o in old.get("overrides", [])]
    cli = [[mode, pat] for mode, pat in overrides]
    old_pages = (old or {}).get("pages", {})
    pages = {}
    for page in sorted(tree.pages, key=lambda x: x.key):
        prev = old_pages.get(page.key)
        usable = prev if prev and (not reset or prev.get("why") == "manual") else None
        rule_keep, rule_why = "full", "llms: all"
        if _host_of(page.url) != tree.main_host:
            rule_keep, rule_why = "stub", "llms: other host"
        keep, why = _choose(page.key, rule_keep, rule_why, stored, cli, usable)
        entry = {"keep": keep, "title": page.title, "section": page.section,
                 "description": page.description or (prev or {}).get("description"),
                 "why": why, "uri": page.url}
        if prev and str(prev.get("why", "")).startswith("model:") and why == prev["why"]:
            entry["description"] = prev.get("description")
        elif reset and why != "manual" and not page.description:
            entry["description"] = None
        for field in CARRIED:
            if prev and field in prev:
                entry[field] = prev[field]
        if why == "llms: other host":
            entry.pop("fetch_error", None)
        pages[page.key] = entry
    return {"format": FORMAT, "kind": "llms", "source": source, "base_url": None,
            "main_host": tree.main_host, "index_sha256": tree.sha256, "indexes": tree.indexes,
            "project": tree.title, "version": "", "entry_count": len(pages),
            "rule": "llms-all", "overrides": stored + cli, "pages": pages}


def _added_dropped(pages: dict, old: Optional[dict]) -> List[str]:
    lines: List[str] = []
    if old is not None:
        added = sorted(set(pages) - set(old.get("pages", {})))
        dropped = sorted(set(old.get("pages", {})) - set(pages))
        for word, keys in (("added", added), ("dropped", dropped)):
            if keys:
                more = " ..." if len(keys) > 10 else ""
                lines.append("%s %d page%s: %s%s" % (word, len(keys), "" if len(keys) == 1
                                                      else "s", ", ".join(keys[:10]), more))
    return lines


def summarize_llms(plan: dict, old: Optional[dict]) -> List[str]:
    """Plan summary lines for an llms.txt plan: counts, sections, the index
    tree, added/dropped pages and a warning over 300 full pages."""
    pages = plan["pages"]
    full = sum(1 for p in pages.values() if p["keep"] == "full")
    lines = ["%s: %d pages: %d full, %d stub"
             % (plan.get("project", ""), len(pages), full, len(pages) - full)]
    sections = Counter((p.get("section") or "Pages").split(" / ")[0] for p in pages.values())
    top = sorted(sections.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    lines.append("  " + "   ".join("%s: %d" % kv for kv in top))
    indexes = plan.get("indexes", [])
    if indexes:
        lines.append("index tree:")
        depth: Dict[Optional[str], int] = {}
        host = plan.get("main_host", urlsplit(plan["source"]).netloc)
        for ix in indexes:
            d = 0 if ix.get("parent") is None else depth.get(ix["parent"], 0) + 1
            depth[ix["url"]] = d
            parts = urlsplit(ix["url"])
            if parts.scheme not in ("http", "https"):
                shown = os.path.basename(ix["url"])  # a local root file
            elif (parts.hostname or "") == host:
                shown = parts.path.lstrip("/")
            else:
                shown = ix["url"]
            info = ix["note"] if ix.get("pages") is None else ix["pages"]
            lines.append("%s%s%s" % ("  " * (d + 1), shown,
                                     "" if info is None else " (%s)" % info))
    lines.extend(_added_dropped(pages, old))
    others = Counter(_host_of(p["uri"]) for p in pages.values()
                     if p.get("why") == "llms: other host" and p.get("uri"))
    if others:
        top = max(others, key=lambda h: (others[h], h))
        lines.append("warning: %d pages on other hosts are stubs (e.g. %s); keep them "
                     "with --full '%s/*'" % (sum(others.values()), top, top))
    if full > 300:
        lines.append("warning: %d full pages; narrow with a sub-index as SOURCE (see the tree) "
                     "or --stub globs" % full)
    return lines


def load_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_plan(path: str, plan: dict) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".plan.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
