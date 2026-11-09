#!/usr/bin/env python3
"""Decide which skills CI must test, from the files changed since a base commit.

    python3 scripts/ci_changed_skills.py --base <sha> [--check-versions]

Prints `skills=<comma list>` (or `skills=all`). In GitHub Actions it also
writes `skills` and `any` (true/false) to $GITHUB_OUTPUT. Rules:
- skills/<name>/...           -> that skill (and, with --check-versions, its
                                 metadata.version must be higher than on base)
- tests/test_<name>.py        -> that skill (name with "_" for "-")
- shared test files, scripts/, .github/ -> every skill
- anything else (notes, docs) -> no skill tests
Exit 1 if a version check fails. Standard library only.
"""
import argparse
import os
import re
import subprocess
import sys

ALL = "all"
SHARED_PREFIXES = (".github/", "scripts/")
SHARED_TESTS = re.compile(r"^tests/(?:_.*|test_skills\.py|test_public_safety\.py|test_ci_changed_skills\.py)$")
VERSION_LINE = re.compile(r'^\s+version:\s*(\S+)\s*$', re.M)


def classify(paths, skills):
    """(skills to test, skills whose own files changed). First may be ALL."""
    test, own = set(), set()
    by_test = {"tests/test_%s.py" % s.replace("-", "_"): s for s in skills}
    for p in paths:
        if p.startswith(SHARED_PREFIXES) or SHARED_TESTS.match(p):
            test = ALL
            continue
        m = re.match(r"^skills/([^/]+)/", p)
        if m:
            if m.group(1) in skills:
                own.add(m.group(1))
                if test is not ALL:
                    test.add(m.group(1))
            continue
        if p in by_test and test is not ALL:
            test.add(by_test[p])
    return test, own


def version_key(raw):
    m = re.fullmatch(r'"?(\d+)\.(\d+)\.(\d+)"?', (raw or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def changed_files(repo, base):
    r = git(repo, "diff", "--name-only", base, "HEAD")
    if r.returncode:
        raise SystemExit("git diff failed: " + r.stderr.strip())
    return [p for p in r.stdout.splitlines() if p]


def skill_version(text):
    m = VERSION_LINE.search(text or "")
    return version_key(m.group(1)) if m else None


def check_versions(repo, base, own):
    """Problems for skills that existed on base but kept or lowered their version."""
    problems = []
    for name in sorted(own):
        rel = "skills/%s/SKILL.md" % name
        old = git(repo, "show", "%s:%s" % (base, rel))
        if old.returncode:
            continue  # new skill: no bump needed
        try:
            with open(os.path.join(repo, rel), encoding="utf-8") as f:
                new_v = skill_version(f.read())
        except FileNotFoundError:
            continue
        old_v = skill_version(old.stdout)
        if new_v is None or old_v is None or new_v <= old_v:
            fmt = lambda v: ".".join(map(str, v)) if v else "?"
            problems.append("%s: version %s -> %s; bump metadata.version (AGENTS.md: updating a skill)"
                            % (name, fmt(old_v), fmt(new_v)))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="commit to compare HEAD against")
    ap.add_argument("--check-versions", action="store_true")
    a = ap.parse_args(argv)
    repo = os.getcwd()
    skills = {d for d in os.listdir(os.path.join(repo, "skills"))
              if os.path.isfile(os.path.join(repo, "skills", d, "SKILL.md"))}
    paths = changed_files(repo, a.base)
    test, own = classify(paths, skills)
    value = ALL if test is ALL else ",".join(sorted(test))
    print("skills=%s" % value)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("skills=%s\nany=%s\n" % (value, "true" if value else "false"))
    if a.check_versions:
        problems = check_versions(repo, a.base, own)
        for p in problems:
            print("::error::" + p)
        if problems:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
