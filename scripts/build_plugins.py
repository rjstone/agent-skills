#!/usr/bin/env python3
"""Build the plugin files from skill-sets.json (one plugin per skill set).

skill-sets.json at the repo root names each set and its skills; every skill
stays in skills/<name>/ (no copies). This script writes:

- .claude-plugin/marketplace.json - the local Claude marketplace. Each set is
  a plugin whose root is skills/ ("source": "./skills") and whose "skills"
  list names only that set's folders. (A repo-root source would load every
  skill: an entry's list adds to the default skills/ scan.)
- opencode-plugin/sets.json - {set: [skill, ...]}, read by the opencode plugin.

    python3 scripts/build_plugins.py           # (re)write both files
    python3 scripts/build_plugins.py --check   # exit 1 if missing or stale

Exit 2 when skill-sets.json is invalid. Standard library only.
"""
import argparse
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
OUTPUTS = {
    "marketplace": os.path.join(".claude-plugin", "marketplace.json"),
    "opencode": os.path.join("opencode-plugin", "sets.json"),
}


class SetsError(Exception):
    """skill-sets.json is invalid (one-line message)."""


def load_sets(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise SetsError("cannot read %s: %s" % (path, e.strerror))
    except ValueError as e:
        raise SetsError("%s is not valid JSON: %s" % (path, e))


def validate(config, skills_dir):
    """Raise SetsError on a rule violation; return warning strings."""
    if not isinstance(config, dict):
        raise SetsError("skill-sets.json must be a JSON object")
    market = config.get("marketplace")
    if not isinstance(market, dict) or not market.get("name") or not isinstance(market.get("owner"), dict):
        raise SetsError('skill-sets.json needs "marketplace" with "name" and "owner"')
    sets = config.get("sets")
    if not isinstance(sets, list) or not sets:
        raise SetsError('skill-sets.json needs a non-empty "sets" list')
    seen, owners = set(), {}
    for s in sets:
        name = s.get("name") if isinstance(s, dict) else None
        if not isinstance(name, str) or not KEBAB.match(name):
            raise SetsError("set name %r is not lowercase kebab-case" % (name,))
        if name in seen:
            raise SetsError('duplicate set name "%s"' % name)
        seen.add(name)
        desc = s.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise SetsError('set "%s" needs a description' % name)
        skills = s.get("skills")
        if not isinstance(skills, list) or not skills or not all(isinstance(k, str) for k in skills):
            raise SetsError('set "%s" needs a non-empty "skills" list of names' % name)
        for skill in skills:
            if not os.path.isfile(os.path.join(skills_dir, skill, "SKILL.md")):
                raise SetsError('set "%s" lists skill "%s", but skills/%s/SKILL.md does not exist'
                                % (name, skill, skill))
            owners.setdefault(skill, []).append(name)
    return ['skill "%s" is in several sets (%s): installing them together loads it twice'
            % (skill, ", ".join(names)) for skill, names in owners.items() if len(names) > 1]


def build_marketplace(config):
    market = config["marketplace"]
    out = {"name": market["name"], "owner": market["owner"]}
    if market.get("description"):
        out["metadata"] = {"description": market["description"]}
    out["plugins"] = [{"name": s["name"], "description": s["description"],
                       "source": "./skills", "skills": ["./" + k for k in s["skills"]]}
                      for s in config["sets"]]
    return out


def build_opencode_sets(config):
    return {s["name"]: list(s["skills"]) for s in config["sets"]}


def render(obj):
    return json.dumps(obj, indent=2) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if an output is missing or stale")
    ap.add_argument("--root", default=REPO_ROOT, help="repo root (default: this repo)")
    args = ap.parse_args(argv)
    try:
        config = load_sets(os.path.join(args.root, "skill-sets.json"))
        warnings = validate(config, os.path.join(args.root, "skills"))
    except SetsError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    for w in warnings:
        print("warning: %s" % w, file=sys.stderr)
    texts = {OUTPUTS["marketplace"]: render(build_marketplace(config)),
             OUTPUTS["opencode"]: render(build_opencode_sets(config))}
    stale = 0
    for rel, text in texts.items():
        path = os.path.join(args.root, rel)
        try:
            with open(path, encoding="utf-8", newline="") as f:
                current = f.read()
        except OSError:
            current = None
        if current == text:
            continue
        if args.check:
            print("%s is %s; run python3 scripts/build_plugins.py"
                  % (rel.replace(os.sep, "/"), "missing" if current is None else "stale"))
            stale = 1
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("wrote %s" % rel.replace(os.sep, "/"))
    return stale


if __name__ == "__main__":
    sys.exit(main())
