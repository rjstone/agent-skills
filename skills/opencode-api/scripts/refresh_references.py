#!/usr/bin/env python3
"""Refresh references/openapi.json, the opencode server's OpenAPI spec.

The docs' API section (https://opencode.ai/docs/api/) is generated from this
file. Fetched with If-None-Match, so an unchanged spec costs a 304; stored
verbatim with LF line endings; references/manifest.json records url, etag
and sha256.

    python refresh_references.py            # download if changed
    python refresh_references.py --check    # no writes; exit 1 if stale
    python refresh_references.py --force    # ignore the ETag

Exit codes: 0 ok / up to date, 1 stale (--check), 2 network or format error.
Standard library only.
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

SPEC_URL = "https://opencode.ai/docs/openapi.json"
PAGE_URL = "https://opencode.ai/docs/api/"
FILE = "openapi.json"
USER_AGENT = "opencode-docs-refresh/1"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FetchError(Exception):
    pass


def normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def http_fetch(url, etag):
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
            return r.status, r.read().decode("utf-8"), r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, None, etag
        raise FetchError("%s: HTTP %s" % (url, e.code)) from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError("%s: %s" % (url, getattr(e, "reason", e))) from e


def errata_ids(text):
    """[errata ids] from '## E01: ...' headings outside fenced examples."""
    ids, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            m = re.match(r"^## (E\d+)\b", line)
            if m:
                ids.append(m.group(1))
    return ids


def refresh(skill_dir, fetch=http_fetch, check=False, force=False, today=None):
    refs = os.path.join(skill_dir, "references")
    manifest_path = os.path.join(refs, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        manifest = {}
    try:
        with open(os.path.join(refs, FILE), encoding="utf-8", newline="") as f:
            on_disk = normalize(f.read())
    except FileNotFoundError:
        on_disk = None
    intact = on_disk is not None and sha256(on_disk) == manifest.get("sha256")
    etag = manifest.get("etag") if intact and not force else None
    try:
        status, body, new_etag = fetch(SPEC_URL, etag)
        if status == 304:
            print("unchanged: %s (304)" % FILE)
            return 0
        text = normalize(body)
        try:
            spec = json.loads(text)
        except ValueError as e:
            raise FetchError("%s: not JSON (%s)" % (SPEC_URL, e))
        if not str(spec.get("openapi", "")).startswith("3."):
            raise FetchError("%s: not an OpenAPI 3 document" % SPEC_URL)
    except FetchError as e:
        print("error: %s" % e)
        return 2
    changed = on_disk is None or sha256(on_disk) != sha256(text)
    if not changed:
        print("unchanged: %s (same content)" % FILE)
        if check:
            return 0
    else:
        print("%s: %s (%d paths, info.version %s)" % ("new" if on_disk is None else "updated", FILE,
                                                       len(spec.get("paths", {})), spec.get("info", {}).get("version")))
        try:
            with open(os.path.join(skill_dir, "ERRATA.md"), encoding="utf-8") as f:
                ids = errata_ids(f.read())
        except FileNotFoundError:
            ids = []
        if ids:
            print("  re-check errata: %s" % ", ".join(ids))
        if check:
            return 1
    os.makedirs(refs, exist_ok=True)
    if changed:
        with open(os.path.join(refs, FILE), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    manifest = {"url": SPEC_URL, "page": PAGE_URL, "etag": new_etag, "sha256": sha256(text),
                "fetched": (today or datetime.date.today().isoformat()) if changed else manifest.get("fetched")}
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="no writes; exit 1 if stale")
    p.add_argument("--force", action="store_true", help="ignore the stored ETag")
    a = p.parse_args(argv)
    return refresh(SKILL_DIR, check=a.check, force=a.force)


if __name__ == "__main__":
    sys.exit(main())
