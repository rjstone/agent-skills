"""Write a built docvol: <cache>/built/<name>/{index.json, db.json, meta.json},
the same files docshelf reads for a DevDocs docvol."""
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
from typing import Dict, List

from build_core import NAME_RE, CLIError, built_dir
from build_html import STUB_CLASS, main_content, rewrite_links, stub_html
from build_inventory import InvEntry, page_key, split_uri

FILES = ("index.json", "db.json", "meta.json")  # meta.json last: docshelf keys on it
_STD_LABELS = {"doc": "Page", "label": "Section", "term": "Term"}


def derive_name(header: dict) -> str:
    """A docvol name from the inventory's project and version:
    "YosysHQ Yosys" -> "yosyshq-yosys"; version "master" -> "...~master"."""
    def clean(text: str) -> str:
        return re.sub(r"[^a-z0-9.+-]+", "-", text.lower()).strip("-.")
    name = clean(header.get("project", "")) or "docs"
    version = clean(header.get("version", ""))
    return name + ("~" + version if version else "")


def check_name(cache: str, name: str) -> None:
    """CLIError(code 2) when name is not a plain docvol name or DevDocs has it
    (then installing it is the better way)."""
    if not NAME_RE.match(name or ""):
        raise CLIError("not a usable docvol name: %r (letters, digits and . _ ~ + -)"
                       % name, 2)
    devdocs = os.path.join(cache, "devdocs")
    slugs = set()
    try:
        with open(os.path.join(devdocs, "docs.json"), encoding="utf-8") as f:
            slugs = {r.get("slug") for r in json.load(f) if isinstance(r, dict)}
    except (OSError, ValueError, AttributeError):
        pass
    if name in slugs or os.path.isdir(os.path.join(devdocs, name)):
        raise CLIError("DevDocs has %s: install it with `docshelf install %s` instead, "
                       "or choose another --name" % (name, name), 2)


def role_label(role: str) -> str:
    domain, _, kind = role.partition(":")
    if domain == "std":
        return _STD_LABELS.get(kind, kind.capitalize())
    return kind or domain


def _entry_name(e: InvEntry) -> str:
    return e.name if e.dispname == "-" else e.dispname


def _index(plan: dict, entries: List[InvEntry]) -> dict:
    pages = plan["pages"]
    seen, out = set(), []

    def add(name: str, kind: str, path: str) -> None:
        if (name, kind, path) not in seen:
            seen.add((name, kind, path))
            out.append({"name": name, "type": kind, "path": path})

    for key, p in pages.items():
        if p["keep"] == "stub":
            add(p["title"], "Guide", key)
    for e in entries:
        page_uri, anchor = split_uri(e.uri)
        key = page_key(page_uri)
        if key not in pages or pages[key]["keep"] != "full":
            continue
        if e.role == "std:label" and e.dispname == "-":
            continue  # an anonymous label: noise
        add(_entry_name(e), role_label(e.role), key + ("#" + anchor if anchor else ""))
    counts: Dict[str, int] = {}
    for x in out:
        counts[x["type"]] = counts.get(x["type"], 0) + 1
    types = [{"name": t, "count": counts[t], "slug": t.lower().replace(" ", "_")}
             for t in sorted(counts)]
    return {"entries": out, "types": types}


def _previous_db(folder: str) -> Dict[str, str]:
    try:
        with open(os.path.join(folder, "db.json"), encoding="utf-8") as f:
            db = json.load(f)
        return db if isinstance(db, dict) else {}
    except (OSError, ValueError):
        return {}


def _db(plan: dict, pages_html: Dict[str, str], errors: Dict[str, str],
        previous: Dict[str, str], reused: List[str]) -> Dict[str, str]:
    """Page HTML by key. A full page that failed keeps its previous stored
    copy (its uri goes in reused) instead of becoming a stub."""
    pages, live = plan["pages"], plan.get("base_url")
    keys_by_uri = {p["uri"]: key for key, p in pages.items()}
    db = {}
    for key, p in pages.items():
        uri = p["uri"]
        url = urllib.parse.urljoin(live, uri) if live else None
        if p["keep"] == "full" and uri in pages_html:
            db[key] = rewrite_links(main_content(pages_html[uri]), key, uri, keys_by_uri, live)
            continue
        old = previous.get(key)
        if p["keep"] == "full" and isinstance(old, str) and STUB_CLASS not in old:
            db[key] = old
            reused.append(uri)
            continue
        if p["keep"] == "full":
            note = errors.get(uri, "not fetched")
        else:
            note = None if url else "left out of the build (source: %s)" % uri
        db[key] = stub_html(p["title"], p.get("section"), p.get("description"), url, note)
    return db


def write_docvol(cache: str, name: str, plan: dict, entries: List[InvEntry],
                 pages_html: Dict[str, str], errors: Dict[str, str], now: float) -> dict:
    """Write the docvol and return its meta. pages_html and errors are keyed
    by inventory page uri. A failure leaves the previous docvol (or none) in
    place and raises CLIError(code 2)."""
    index = _index(plan, entries)
    folder = os.path.join(built_dir(cache), name)
    reused: List[str] = []
    db = _db(plan, pages_html, errors, _previous_db(folder), reused)
    meta = {"slug": name, "name": plan.get("project") or name,
            "release": plan.get("version", ""), "version": plan.get("version", ""),
            "mtime": int(now),
            "installedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "alias": None, "entry_count": len(index["entries"]),
            "origin": "docshelf-build", "source": plan["source"],
            "inventory_sha256": plan["inventory_sha256"], "reused": sorted(reused)}
    data = {"index.json": index, "db.json": db, "meta.json": meta}
    created = not os.path.isdir(folder)
    tmps: Dict[str, str] = {}
    baks: Dict[str, str] = {}
    try:
        os.makedirs(folder, exist_ok=True)
        for fname in FILES:
            fd, tmps[fname] = tempfile.mkstemp(dir=folder, prefix="." + fname + ".")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data[fname], f, ensure_ascii=False)
            path = os.path.join(folder, fname)
            if os.path.exists(path):
                baks[fname] = path + ".bak"
                shutil.copyfile(path, baks[fname])
        for fname in FILES:
            os.replace(tmps[fname], os.path.join(folder, fname))
            del tmps[fname]
    except OSError as e:
        for t in tmps.values():
            _unlink(t)
        if created:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            for fname in FILES:
                path = os.path.join(folder, fname)
                if fname in baks:
                    shutil.copyfile(baks[fname], path)  # not os.replace: it just failed
                else:
                    _unlink(path)
        raise CLIError("cannot write %s: %s" % (folder, e), 2)
    finally:
        for b in baks.values():
            _unlink(b)
    return meta


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
