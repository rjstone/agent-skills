"""Offline tests for skills/docshelf-build. No network: inventories are made
by make_inv() and sites are folders or fake openers. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
import zlib
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("docshelf-build"):
    raise unittest.SkipTest("docshelf-build not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO_ROOT, "skills", "docshelf-build")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import build_core  # noqa: E402
from build_core import CLIError  # noqa: E402
from build_inventory import InvEntry, parse_inventory, page_key, split_uri  # noqa: E402
from build_plan import load_plan, make_plan, save_plan, summarize  # noqa: E402


def make_inv(entries: List[Tuple[str, str, str, str, str]], project: str = "Demo",
             version: str = "1.0") -> bytes:
    """A Sphinx v2 inventory; entries are (name, role, priority, uri, dispname)."""
    head = ("# Sphinx inventory version 2\n# Project: %s\n# Version: %s\n"
            "# The remainder of this file is compressed using zlib.\n"
            % (project, version)).encode()
    body = "".join("%s %s %s %s %s\n" % e for e in entries).encode()
    return head + zlib.compress(body)


class InventoryTests(unittest.TestCase):
    def test_parse_expands_dollar_and_keeps_dash_dispname(self):
        hdr, es = parse_inventory(make_inv([("opt", "cmd:cmd", "1", "cmd/opt.html#$", "-")]))
        self.assertEqual(hdr, {"project": "Demo", "version": "1.0"})
        self.assertEqual(es[0].uri, "cmd/opt.html#opt")
        self.assertEqual(es[0].dispname, "-")
        self.assertEqual((es[0].role, es[0].priority), ("cmd:cmd", 1))

    def test_names_with_spaces(self):
        _, es = parse_inventory(make_inv([("my label", "std:label", "-1", "a.html#x", "My Label")]))
        self.assertEqual(es[0].name, "my label")
        self.assertEqual(es[0].priority, -1)
        self.assertEqual(es[0].dispname, "My Label")

    def test_name_with_a_number_word(self):
        # real Yosys entry: a bare "10" inside the name must not pass as the priority
        name = "cmd/x:intel alm (cyclone v, arria v, cyclone 10 gx)"
        _, es = parse_inventory(make_inv([(name, "std:label", "-1", "cmd/x.html#alm", "Intel ALM")]))
        self.assertEqual([(e.name, e.role) for e in es], [(name, "std:label")])

    def test_split_uri(self):
        self.assertEqual(split_uri("cmd/opt.html#opt"), ("cmd/opt.html", "opt"))
        self.assertEqual(split_uri("guide/a.html"), ("guide/a.html", None))

    def test_page_keys(self):
        self.assertEqual(page_key("cmd/opt.html"), "cmd/opt")
        self.assertEqual(page_key("api/foo/"), "api/foo")
        self.assertEqual(page_key(""), "index")
        self.assertEqual(page_key("index.html"), "index")

    def test_rejects_v1_and_garbage(self):
        for data in (b"# Sphinx inventory version 1\n# Project: x\n# Version: 1\nfoo mod foo.html\n",
                     b"<html>not found</html>"):
            with self.assertRaises(CLIError) as c:
                parse_inventory(data)
            self.assertEqual(c.exception.code, 3)

    def test_version_constant(self):
        self.assertRegex(build_core.VERSION, r"^\d+\.\d+\.\d+$")


SRC = "https://x.io/docs/"
HDR = {"project": "Demo", "version": "1.0"}


def inv(*rows):
    """InvEntry list from (name, role, uri, dispname) rows."""
    return [InvEntry(n, r, 1, u, d) for n, r, u, d in rows]


ENTRIES = inv(("index", "std:doc", "index.html", "Demo"),
              ("opt", "cmd:cmd", "cmd/opt.html#opt", "-"),
              ("cmd/opt", "std:doc", "cmd/opt.html", "opt - optimize"),
              ("guide/index", "std:doc", "guide/index.html", "Guides"),
              ("guide/a", "std:doc", "guide/a.html", "Guide A"),
              ("guide-a-sec", "std:label", "guide/a.html#sec", "A section"),
              ("guide/b", "std:doc", "guide/b.html", "Guide B"))
STD_ONLY_ENTRIES = [e for e in ENTRIES if e.role.startswith("std:")]


class PlanTests(unittest.TestCase):
    def test_role_rule(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [])
        self.assertEqual(p["format"], 1)
        self.assertEqual(p["pages"]["cmd/opt"]["keep"], "full")
        self.assertEqual(p["pages"]["cmd/opt"]["why"], "roles: cmd:cmd")
        self.assertEqual(p["pages"]["cmd/opt"]["uri"], "cmd/opt.html")
        self.assertEqual(p["pages"]["guide/a"]["keep"], "stub")
        self.assertEqual(p["pages"]["guide/a"]["why"], "roles: std only")
        self.assertIsNone(p["pages"]["guide/a"]["description"])

    def test_overrides_last_wins_and_append(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [("full", "guide/*")])
        p = make_plan(SRC, "h", HDR, ENTRIES, [("stub", "guide/a")], old=p)
        self.assertEqual(p["overrides"], [["full", "guide/*"], ["stub", "guide/a"]])
        self.assertEqual(p["pages"]["guide/a"]["keep"], "stub")
        self.assertEqual(p["pages"]["guide/b"]["keep"], "full")
        self.assertEqual(p["pages"]["guide/b"]["why"], "override: guide/*")

    def test_all_and_reset(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [("full", "*")])
        self.assertTrue(all(v["keep"] == "full" for v in p["pages"].values()))
        p = make_plan(SRC, "h", HDR, ENTRIES, [], old=p, reset=True)
        self.assertEqual(p["overrides"], [])
        self.assertEqual(p["pages"]["guide/a"]["keep"], "stub")

    def test_manual_beats_override_and_survives(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [])
        p["pages"]["guide/a"].update(keep="full", why="manual")
        p = make_plan(SRC, "h2", HDR, ENTRIES, [("stub", "guide/*")], old=p)
        self.assertEqual(p["pages"]["guide/a"]["keep"], "full")
        self.assertEqual(p["pages"]["guide/a"]["why"], "manual")
        self.assertEqual(p["inventory_sha256"], "h2")

    def test_inventory_change_adds_and_drops(self):
        old = make_plan(SRC, "h", HDR, ENTRIES, [])
        old["pages"]["guide/a"].update(keep="full", why="manual")
        new_entries = [e for e in ENTRIES if not e.uri.startswith("guide/a")] + \
            inv(("c", "cmd:cmd", "cmd/c.html#c", "-"))
        p = make_plan(SRC, "h2", HDR, new_entries, [], old=old)
        self.assertNotIn("guide/a", p["pages"])
        self.assertEqual(p["pages"]["cmd/c"]["keep"], "full")
        lines = summarize(p, old)
        self.assertTrue(any("added 1" in l and "cmd/c" in l for l in lines), lines)
        self.assertTrue(any("dropped 1" in l and "guide/a" in l for l in lines), lines)

    def test_titles_and_sections(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [])
        self.assertEqual(p["pages"]["guide/a"]["title"], "Guide A")
        self.assertEqual(p["pages"]["guide/a"]["section"], "Guides")
        self.assertEqual(p["pages"]["cmd/opt"]["section"], "cmd")
        self.assertIsNone(p["pages"]["index"]["section"])

    def test_summary_counts(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [])
        text = "\n".join(summarize(p, None))
        self.assertIn("1 full, 4 stub", text)
        self.assertIn("7 entries", text)

    def test_all_stub_warning(self):
        lines = summarize(make_plan(SRC, "h", HDR, STD_ONLY_ENTRIES, []), None)
        self.assertTrue(any("no page has a domain role" in l and "--full 'guide/*'" in l
                            for l in lines), lines)

    def test_base_url(self):
        self.assertEqual(make_plan(SRC, "h", HDR, ENTRIES, [])["base_url"], SRC)
        with tempfile.TemporaryDirectory() as d:
            p = make_plan(d, "h", HDR, ENTRIES, [])
            self.assertIsNone(p["base_url"])
            p = make_plan(d, "h", HDR, ENTRIES, [], old=p, base_url="https://y.org/")
            self.assertEqual(p["base_url"], "https://y.org/")
            p = make_plan(d, "h", HDR, ENTRIES, [], old=p)
            self.assertEqual(p["base_url"], "https://y.org/")

    def test_save_and_load(self):
        p = make_plan(SRC, "h", HDR, ENTRIES, [("full", "guide/*")])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "demo.json")
            save_plan(path, p)
            self.assertEqual(load_plan(path), p)
            self.assertEqual(os.listdir(os.path.dirname(path)), ["demo.json"])


if __name__ == "__main__":
    unittest.main()
