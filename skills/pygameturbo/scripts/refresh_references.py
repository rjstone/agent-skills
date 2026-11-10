#!/usr/bin/env python3
"""Refresh references/ from the Pygame Turbo docs sources (doc/*.rst).

Pages are fetched verbatim from https://github.com/Mambouna/pgturbo at one
commit and stored under references/ with the same relative path (doc/a/b.rst
-> references/a/b.rst), LF line endings. references/manifest.json records the
commit and, per page, its docs URL and sha256 (of the LF text). The upstream
license (LGPL-3.0) is copied to references/COPYING.

    python refresh_references.py --ref main      # resolve main, fetch, write
    python refresh_references.py --ref <sha>     # a 40-hex commit: no API call
    python refresh_references.py --check         # no writes; exit 1 if the
                                                 # committed files differ from
                                                 # the manifest's commit

Exit codes: 0 ok / up to date, 1 stale or edited (--check), 2 network error.
Standard library only, so it runs the same on Windows, macOS and Linux.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = "Mambouna/pgturbo"
RAW = "https://raw.githubusercontent.com/" + REPO + "/{ref}/{path}"
API_COMMIT = "https://api.github.com/repos/" + REPO + "/commits/{ref}"
DOCS = "https://pgturbo.readthedocs.io/{page}.html"
USER_AGENT = "pgturbo-docs-refresh/1"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Vendored pages, relative to doc/ without ".rst". Not vendored (read online):
# the full example-game walkthroughs, contributing/, misc/changelog,
# misc/other_libs.
PAGES = [
    "overview",
    "tutorials/1_introduction",
    "tutorials/2_game_mechanics",
    "tutorials/3_images_sounds_and_music",
    "tutorials/4_animating_actors",
    "tutorials/from_scratch",
    "deep_dives/installation_and_running",
    "deep_dives/update_draw_cycle",
    "deep_dives/actors",
    "deep_dives/screen",
    "deep_dives/game_window",
    "deep_dives/player_input",
    "deep_dives/hooks",
    "deep_dives/clock",
    "deep_dives/audio",
    "deep_dives/resources_and_storage",
    "deep_dives/property_animation",
    "references/actor",
    "references/animate",
    "references/animations",
    "references/clock",
    "references/colors_ref",
    "references/fonts",
    "references/game_window",
    "references/hooks",
    "references/images",
    "references/joystick",
    "references/keyboard",
    "references/mouse",
    "references/music",
    "references/scratch",
    "references/screen",
    "references/sounds",
    "references/storage",
    "references/tone",
    "examples/overview",
    "misc/resources",
]
LICENSE_FILE = "COPYING"


class FetchError(Exception):
    pass


def normalize(text):
    """LF line endings, no BOM."""
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_sha(ref):
    return re.fullmatch(r"[0-9a-f]{40}", ref) is not None


def http_get(url, accept=None):
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return r.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"{url}: {e}") from e


def resolve(ref, get=http_get):
    """A commit sha for a branch, tag or sha."""
    if is_sha(ref):
        return ref
    sha = get(API_COMMIT.format(ref=ref), accept="application/vnd.github.sha").strip()
    if not is_sha(sha):
        raise FetchError(f"could not resolve {ref!r} to a commit")
    return sha


def fetch_all(commit, get=http_get):
    """{relative file: LF text} for every page and the license."""
    files = {}
    for page in PAGES:
        files[page + ".rst"] = normalize(get(RAW.format(ref=commit, path=f"doc/{page}.rst")))
    files[LICENSE_FILE] = normalize(get(RAW.format(ref=commit, path=LICENSE_FILE)))
    return files


def build_manifest(commit, files):
    return {
        "repo": "https://github.com/" + REPO,
        "commit": commit,
        "license": "LGPL-3.0 (see COPYING)",
        "pages": {
            name: {
                "url": DOCS.format(page=name[: -len(".rst")]) if name.endswith(".rst") else None,
                "sha256": sha256(text),
            }
            for name, text in sorted(files.items())
        },
    }


def read_lf(path):
    with open(path, encoding="utf-8", newline="") as f:
        return normalize(f.read())


def committed_problems(refs_dir):
    """Files that are missing, extra or differ from references/manifest.json."""
    with open(os.path.join(refs_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    problems = []
    for name, entry in manifest["pages"].items():
        path = os.path.join(refs_dir, name)
        if not os.path.exists(path):
            problems.append(f"missing: {name}")
        elif sha256(read_lf(path)) != entry["sha256"]:
            problems.append(f"edited: {name} (never hand-edit references/)")
    for root, _, names in os.walk(refs_dir):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), refs_dir).replace(os.sep, "/")
            if rel not in manifest["pages"] and rel not in ("manifest.json", "README.md"):
                problems.append(f"not in manifest: {rel}")
    return problems


def write(refs_dir, files, manifest):
    for name, text in files.items():
        path = os.path.join(refs_dir, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    with open(os.path.join(refs_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def main(argv=None, get=http_get, skill_dir=SKILL_DIR):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ref", help="branch, tag or 40-hex commit to fetch (default: the manifest's commit)")
    p.add_argument("--check", action="store_true", help="report differences, write nothing")
    a = p.parse_args(argv)
    refs_dir = os.path.join(skill_dir, "references")
    try:
        if a.check:
            problems = committed_problems(refs_dir)
            for line in problems:
                print(line)
            if not a.ref:
                return 1 if problems else 0
        if a.ref:
            commit = resolve(a.ref, get)
        else:
            with open(os.path.join(refs_dir, "manifest.json"), encoding="utf-8") as f:
                commit = json.load(f)["commit"]
        files = fetch_all(commit, get)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    manifest = build_manifest(commit, files)
    if a.check:
        with open(os.path.join(refs_dir, "manifest.json"), encoding="utf-8") as f:
            current = json.load(f)
        stale = current != manifest
        print(f"{'stale' if stale else 'up to date'}: {commit[:12]}")
        return 1 if stale else 0
    write(refs_dir, files, manifest)
    print(f"wrote {len(files)} files from {REPO}@{commit[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
