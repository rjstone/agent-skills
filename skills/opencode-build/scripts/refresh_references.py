#!/usr/bin/env python3
"""Refresh references/*.md from the opencode v2 docs (the "## Build" section).

The page list comes from https://opencode.ai/docs/llms.txt, so new pages are
picked up and removed ones reported. Each page is fetched as Markdown
(canonical URL minus trailing "/" plus ".md") with If-None-Match, so an
unchanged page costs a 304. Files are stored verbatim with LF line endings;
references/manifest.json records url, etag and sha256 (of the LF text) per page.

    python refresh_references.py            # download what changed
    python refresh_references.py --check    # no writes; exit 1 if stale
    python refresh_references.py --force    # ignore ETags, re-download all
    python refresh_references.py --prune    # also delete pages no longer listed

Exit codes: 0 ok / up to date, 1 stale (--check), 2 network or index error.
Standard library only, so it runs the same on Windows, macOS and Linux.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

INDEX_URL = "https://opencode.ai/docs/llms.txt"
SECTION = "Build"
BASE_URL = "https://opencode.ai/docs/build/"
USER_AGENT = "opencode-docs-refresh/1"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FetchError(Exception):
    def __init__(self, url, reason):
        super().__init__(f"{url}: {reason}")
        self.url = url


def parse_section(index_text, section):
    """Canonical page URLs listed under '## <section>' (up to the next '## ')."""
    urls, inside = [], False
    for line in index_text.splitlines():
        if line.startswith("## "):
            inside = line[3:].strip() == section
            continue
        if inside:
            urls += re.findall(r"\]\((https://[^)\s]+)\)", line)
    return urls


def md_url(url):
    return url.rstrip("/") + ".md"


def page_file(url):
    rest = url[len(BASE_URL):].strip("/") if url.startswith(BASE_URL) else ""
    return (rest.replace("/", "-") or "intro") + ".md"


def normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def errata_ids(errata_text):
    """{reference file: [errata ids]} from '## E01: ...' entries with a '- Page: `x.md`' line."""
    out, current, fenced = {}, None, False
    for line in errata_text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = re.match(r"^## (E\d+)\b", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"^- Page: `([^`]+\.md)`", line)
        if m and current:
            out.setdefault(m.group(1), []).append(current)
    return out


def http_fetch(url, etag):
    """(status, body, etag) for a GET; status is 200 or 304."""
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return r.status, r.read().decode("utf-8"), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, None, etag
        raise FetchError(url, f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(url, str(getattr(e, "reason", e))) from e


def _read_lf(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return normalize(f.read())
    except FileNotFoundError:
        return None


def refresh(skill_dir, fetch=http_fetch, check=False, force=False, prune=False, today=None):
    refs = os.path.join(skill_dir, "references")
    manifest_path = os.path.join(refs, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        manifest = {"index": INDEX_URL, "section": SECTION, "pages": {}}
    pages = manifest["pages"]
    today = today or datetime.date.today().isoformat()

    try:
        status, index, _ = fetch(INDEX_URL, None)
        urls = parse_section(index or "", SECTION)
        if not urls:
            raise FetchError(INDEX_URL, f'no "## {SECTION}" section with links')
        new, updated, unchanged, writes = [], [], [], {}
        for url in urls:
            name = page_file(url)
            entry = pages.get(name, {})
            on_disk = _read_lf(os.path.join(refs, name))
            # Trust the stored ETag only while the file still matches its hash;
            # a hand-edited (or missing) file is re-downloaded.
            intact = on_disk is not None and sha256(on_disk) == entry.get("sha256")
            etag = entry.get("etag") if intact and not force else None
            status, body, new_etag = fetch(md_url(url), etag)
            if status == 304:
                unchanged.append(name)
                continue
            text = normalize(body)
            record = {"url": url, "md_url": md_url(url), "etag": new_etag, "sha256": sha256(text)}
            if on_disk is not None and sha256(on_disk) == record["sha256"]:
                unchanged.append(name)
                record["fetched"] = entry.get("fetched", today)
            else:
                (updated if on_disk is not None else new).append(name)
                record["fetched"] = today
                writes[name] = text
            pages[name] = record
    except FetchError as e:
        print(f"error: {e}")
        return 2

    listed = {page_file(u) for u in urls}
    removed = sorted(n for n in pages if n not in listed)

    print(f"new: {len(new)}  updated: {len(updated)}  removed: {len(removed)}  unchanged: {len(unchanged)}")
    for label, names in (("new", new), ("updated", updated), ("removed", removed)):
        for n in names:
            print(f"  {label}: {n}")
    try:
        with open(os.path.join(skill_dir, "ERRATA.md"), encoding="utf-8") as f:
            errata = errata_ids(f.read())
    except FileNotFoundError:
        errata = {}
    for n in updated + (removed if prune else []):
        if n in errata:
            print(f"  re-check errata: {', '.join(errata[n])} ({n} changed)")
    if removed and not prune:
        print("  (removed pages kept; run with --prune to delete them)")

    if check:
        return 1 if (new or updated or removed) else 0

    os.makedirs(refs, exist_ok=True)
    for name, text in writes.items():
        with open(os.path.join(refs, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if prune:
        for n in removed:
            pages.pop(n, None)
            try:
                os.remove(os.path.join(refs, n))
            except FileNotFoundError:
                pass
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="no writes; exit 1 if anything is stale")
    p.add_argument("--force", action="store_true", help="ignore stored ETags and re-download")
    p.add_argument("--prune", action="store_true", help="delete pages no longer in the index")
    a = p.parse_args(argv)
    return refresh(SKILL_DIR, check=a.check, force=a.force, prune=a.prune)


if __name__ == "__main__":
    sys.exit(main())
