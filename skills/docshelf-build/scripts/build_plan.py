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

from build_inventory import InvEntry, page_key, split_uri

FORMAT = 1


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _group(key: str) -> str:
    return key.split("/", 1)[0]


def _generated(key: str) -> bool:
    """Sphinx's generated pages (general index, module indexes, search): the
    inventory lists them, the site may not have them, and they hold nothing
    a lookup needs."""
    return key in ("genindex", "search") or ("/" not in key and key.endswith("modindex"))


def make_plan(source: str, inv_sha256: str, header: dict, entries: List[InvEntry],
              overrides: List[Tuple[str, str]], old: Optional[dict] = None,
              reset: bool = False, base_url: Optional[str] = None) -> dict:
    """A plan for entries. With old, its overrides come first (unless reset),
    its base_url is kept unless given, and its "manual" pages keep their
    choice; pages no longer in the inventory are dropped."""
    stored = [] if (old is None or reset) else [list(o) for o in old.get("overrides", [])]
    all_overrides = stored + [[mode, pat] for mode, pat in overrides]
    if _is_url(source):
        live = source
    else:
        live = base_url or (old or {}).get("base_url")

    roles: Dict[str, set] = defaultdict(set)
    uris: Dict[str, str] = {}
    titles: Dict[str, str] = {}
    for e in entries:
        page_uri, _ = split_uri(e.uri)
        key = page_key(page_uri)
        roles[key].add(e.role)
        uris.setdefault(key, page_uri)
        if e.role == "std:doc":
            titles[key] = e.name if e.dispname == "-" else e.dispname

    old_pages = (old or {}).get("pages", {})
    pages = {}
    for key in sorted(roles):
        if _generated(key):
            continue
        domain = sorted(r for r in roles[key] if not r.startswith("std:"))
        keep, why = ("full", "roles: " + ", ".join(domain)) if domain \
            else ("stub", "roles: std only")
        for mode, pat in all_overrides:
            if fnmatch.fnmatchcase(key, pat):
                keep, why = mode, "override: " + pat
        prev = old_pages.get(key)
        if prev and prev.get("why") == "manual":
            keep, why = prev["keep"], "manual"
        if "/" in key:
            group = _group(key)
            section = titles.get(group + "/index", group)
        else:
            section = None
        pages[key] = {"keep": keep, "title": titles.get(key, key), "section": section,
                      "description": (prev or {}).get("description"), "why": why,
                      "uri": uris[key]}
    return {"format": FORMAT, "source": source, "base_url": live,
            "inventory_sha256": inv_sha256,
            "project": header.get("project", ""), "version": header.get("version", ""),
            "entry_count": len(entries), "rule": "roles",
            "overrides": all_overrides, "pages": pages}


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
    for g in biggest[:5]:
        lines.append("  %s: %d full, %d stub" % (g, groups[g]["full"], groups[g]["stub"]))
    if old is not None:
        added = sorted(set(pages) - set(old.get("pages", {})))
        dropped = sorted(set(old.get("pages", {})) - set(pages))
        for word, keys in (("added", added), ("dropped", dropped)):
            if keys:
                more = " ..." if len(keys) > 10 else ""
                lines.append("%s %d page%s: %s%s" % (word, len(keys), "" if len(keys) == 1
                                                      else "s", ", ".join(keys[:10]), more))
    if full == 0 and biggest:
        top = next((g for g in biggest if any("/" in k for k in pages if _group(k) == g)),
                   biggest[0])
        lines.append("warning: no page has a domain role (every entry is std:*), so the "
                     "rule keeps nothing in full; for prose reference use --full '%s/*' "
                     "(or another group above)" % top)
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
