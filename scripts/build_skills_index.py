#!/usr/bin/env python3
"""Build skills/index.json: the opencode HTTP skill catalog for this repo.

opencode loads a `skills` config entry that is an http(s) URL as a catalog:
it fetches `<url>index.json`, then each listed file from
`<url>/<name>/<file>`, and refreshes its cache only when `version` changes.
Served from https://raw.githubusercontent.com/rjstone/agent-skills/main/skills/

    python3 scripts/build_skills_index.py           # (re)write skills/index.json
    python3 scripts/build_skills_index.py --check   # exit 1 if missing or stale

One entry per skills/<name>/SKILL.md, sorted by name; version is the skill's
metadata.version; files are every file in the skill folder (sorted, "/"
separators, no __pycache__/.pyc). Standard library only.
"""
import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = re.compile(r'^\s+version:\s*"?([^"\s]+)"?\s*$', re.M)
FRONTMATTER = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)


def skill_version(skill_md_path):
    with open(skill_md_path, encoding="utf-8") as f:
        m = FRONTMATTER.match(f.read())
    v = VERSION.search(m.group(1)) if m else None
    if not v:
        raise SystemExit("no metadata.version in %s" % skill_md_path)
    return v.group(1)


def skill_files(skill_dir):
    out = []
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), skill_dir)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def build_index(skills_dir):
    entries = []
    for name in sorted(os.listdir(skills_dir)):
        d = os.path.join(skills_dir, name)
        md = os.path.join(d, "SKILL.md")
        if not os.path.isfile(md):
            continue
        entries.append({"name": name, "version": skill_version(md), "files": skill_files(d)})
    return {"skills": entries}


def render(index):
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if skills/index.json is missing or stale")
    ap.add_argument("--skills-dir", default=os.path.join(REPO_ROOT, "skills"))
    a = ap.parse_args(argv)
    path = os.path.join(a.skills_dir, "index.json")
    text = render(build_index(a.skills_dir))
    try:
        with open(path, encoding="utf-8", newline="") as f:
            current = f.read().replace("\r\n", "\n")
    except FileNotFoundError:
        current = None
    if a.check:
        if current == text:
            print("skills/index.json is up to date")
            return 0
        print("skills/index.json is %s: run python3 scripts/build_skills_index.py"
              % ("missing" if current is None else "stale"))
        return 1
    if current != text:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("wrote %s" % os.path.relpath(path, REPO_ROOT))
    else:
        print("skills/index.json already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
