"""Offline tests for skills/docshelf-build. No network: inventories are made
by make_inv() and sites are folders or fake openers. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess  # nosec B404 - runs this repo's own scripts, fixed argv, no shell
import sys
import tempfile
import unittest
import zlib
from unittest import mock
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("docshelf-build"):
    raise unittest.SkipTest("docshelf-build not selected (SKILLS)")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO_ROOT, "skills", "docshelf-build")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import build_core  # noqa: E402
from build_core import CLIError  # noqa: E402
from build_inventory import InvEntry, parse_inventory, page_key, split_uri  # noqa: E402
from build_plan import load_plan, make_llms_plan, make_plan, save_plan, summarize, summarize_llms  # noqa: E402
import build_fetch  # noqa: E402
from build_fetch import (FetchError, PageCache, fetch_llms, fetch_llms_page, fetch_pages,  # noqa: E402
                         index_getter, looks_html, normalize_source, open_source,
                         open_url_source)
from build_html import headings, main_content, rewrite_links, rewrite_url_links, stub_html  # noqa: E402
from build_docvol import check_name, derive_name, role_label, write_docvol, write_llms_docvol  # noqa: E402
import docshelf_build  # noqa: E402
from build_classify import (RULES_ID, apply_choices, parse_choices, bucket, counts, may_decide, preview, review_lines,  # noqa: E402
                            rule_choice, run_rules)
from build_llms import LlmsPage, Tree, is_llms_source, parse_index, read_tree, url_key  # noqa: E402
from build_markdown import front_matter, md_to_html, page_signals, slugify  # noqa: E402
import build_doxygen  # noqa: E402
from build_doxygen import (DoxygenFormatError, js_value, member_name, page_uri,  # noqa: E402
                           menu_pages, parse_list_page, parse_member_page, read_menu_index,
                           read_doxygen, read_search_index, site_header)

DOCSHELF = os.path.join(REPO_ROOT, "skills", "docshelf", "scripts", "docshelf.py")


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

    def test_uri_with_unescaped_spaces(self):
        # real Yosys line: the anchor "opt_clean.opt_clean [options] [selection]" was
        # written unescaped, so its tail spills into the display name
        line = ("opt_clean::opt_clean [options] [selection] cmd:cmdusage 1 "
                "cmd/index_passes_opt.html#opt_clean.opt_clean [options] [selection] "
                "opt_clean [options] [selection]\n")
        data = make_inv([]).split(b"\n", 4)
        data[4] = zlib.compress(line.encode())
        _, es = parse_inventory(b"\n".join(data))
        self.assertEqual(es[0].name, "opt_clean::opt_clean [options] [selection]")
        self.assertEqual(es[0].uri,
                         "cmd/index_passes_opt.html#opt_clean.opt_clean [options] [selection]")
        self.assertEqual(es[0].dispname, "opt_clean [options] [selection]")

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

    def test_no_warning_once_something_is_full(self):
        lines = summarize(make_plan(SRC, "h", HDR, STD_ONLY_ENTRIES, [("full", "guide/*")]), None)
        self.assertFalse(any("no page has a domain role" in l for l in lines), lines)

    def test_sphinx_generated_pages_left_out(self):
        extra = inv(("genindex", "std:label", "genindex.html", "Index"),
                    ("py-modindex", "std:label", "py-modindex.html", "Module Index"),
                    ("modindex", "std:label", "py-modindex.html", "Module Index"),
                    ("search", "std:label", "search.html", "Search Page"))
        p = make_plan(SRC, "h", HDR, ENTRIES + extra, [("full", "*")])
        for key in ("genindex", "py-modindex", "search"):
            self.assertNotIn(key, p["pages"])
        self.assertIn("index", p["pages"])

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

    def test_kind_sphinx(self):
        self.assertEqual(make_plan(SRC, "h", HDR, ENTRIES, [])["kind"], "sphinx")

    def test_sphinx_model_choice_kept(self):
        old = make_plan(SRC, "h", HDR, ENTRIES, [])
        old["pages"]["guide/a"].update(keep="full", why="model:x", description="d", signals={"words": 9})
        p = make_plan(SRC, "h2", HDR, ENTRIES, [], old=old)
        a = p["pages"]["guide/a"]
        self.assertEqual((a["keep"], a["why"], a["description"]), ("full", "model:x", "d"))
        p = make_plan(SRC, "h2", HDR, ENTRIES, [("stub", "guide/*")], old=old)
        self.assertEqual(p["pages"]["guide/a"]["why"], "override: guide/*")
        p = make_plan(SRC, "h2", HDR, ENTRIES, [], old=old, reset=True)
        self.assertEqual(p["pages"]["guide/a"]["why"], "roles: std only")


SRC_LLMS = "https://x.io/llms.txt"


def llms_tree(pages, indexes=None, sha="s1", title="OpenCode"):
    return Tree(title, "x.io",
                [LlmsPage(k, "https://x.io/%s.md" % k, k.upper(), sec, None) for k, sec in pages],
                indexes or [{"url": SRC_LLMS, "title": title, "pages": len(pages),
                             "parent": None, "note": None}], sha)


class LlmsPlanTests(unittest.TestCase):
    def test_all_full(self):
        plan = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs"), ("pricing", "Optional")]), [])
        self.assertEqual((plan["kind"], plan["rule"], plan["project"], plan["version"]),
                         ("llms", "llms-all", "OpenCode", ""))
        self.assertEqual({k: (p["keep"], p["why"]) for k, p in plan["pages"].items()},
                         {"docs/a": ("full", "llms: all"), "pricing": ("full", "llms: all")})
        self.assertEqual(plan["pages"]["docs/a"]["uri"], "https://x.io/docs/a.md")
        self.assertEqual((plan["entry_count"], plan["index_sha256"], plan["base_url"]), (2, "s1", None))

    def test_model_choice_survives_replan_but_not_cli_override_or_reset(self):
        old = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs"), ("docs/b", "Docs")]), [])
        old["pages"]["docs/a"].update(keep="stub", why="model:emb-1", description="guide",
                                      signals={"words": 9})
        again = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs"), ("docs/b", "Docs")], sha="s2"),
                               [], old=old)
        self.assertEqual((again["pages"]["docs/a"]["keep"], again["pages"]["docs/a"]["why"],
                          again["pages"]["docs/a"]["signals"]), ("stub", "model:emb-1", {"words": 9}))
        cli = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs")]), [("full", "docs/*")], old=old)
        self.assertEqual(cli["pages"]["docs/a"]["why"], "override: docs/*")
        reset = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs")]), [], old=old, reset=True)
        self.assertEqual(reset["pages"]["docs/a"]["why"], "llms: all")

    def test_model_choice_keeps_description(self):
        old = make_llms_plan(SRC_LLMS, llms_tree([("a", "Docs")]), [])
        old["pages"]["a"].update(keep="stub", why="model:emb-1", description="model words")
        tree = llms_tree([("a", "Docs")], sha="s2")
        tree = tree._replace(pages=[tree.pages[0]._replace(description="index note")])
        again = make_llms_plan(SRC_LLMS, tree, [], old=old)
        self.assertEqual(again["pages"]["a"]["description"], "model words")
        fresh = make_llms_plan(SRC_LLMS, tree, [])
        self.assertEqual(fresh["pages"]["a"]["description"], "index note")

    def test_summary_local_source_paths(self):
        tree = llms_tree([("a", "Docs")], indexes=[
            {"url": "docs/llms.txt", "title": "R", "pages": 1, "parent": None, "note": None},
            {"url": "https://x.io/_llms/py.txt", "title": "P", "pages": 2,
             "parent": "docs/llms.txt", "note": None},
            {"url": "https://x.io/_llms/deep.txt", "title": "D", "pages": None,
             "parent": "docs/llms.txt", "note": None}])
        plan = make_llms_plan("docs/llms.txt", tree, [])
        self.assertEqual(plan["main_host"], "x.io")
        lines = summarize_llms(plan, None)
        self.assertEqual(lines[2:5], ["index tree:", "  llms.txt (1)", "    _llms/py.txt (2)"])
        self.assertIn("    _llms/deep.txt", lines)
        self.assertFalse(any("None" in l for l in lines), lines)

    def test_manual_beats_cli_and_reset(self):
        old = make_llms_plan(SRC_LLMS, llms_tree([("a", "Docs")]), [])
        old["pages"]["a"].update(keep="stub", why="manual")
        p = make_llms_plan(SRC_LLMS, llms_tree([("a", "Docs")]), [("full", "*")], old=old, reset=True)
        self.assertEqual((p["pages"]["a"]["keep"], p["pages"]["a"]["why"]), ("stub", "manual"))

    def test_summary(self):
        tree = llms_tree([("a", "Docs"), ("b", "Docs"), ("c", "Optional")],
                         indexes=[{"url": "https://x.io/llms.txt", "title": "R", "pages": 1,
                                   "parent": None, "note": None},
                                  {"url": "https://x.io/_llms/python.txt", "title": "P", "pages": 2,
                                   "parent": "https://x.io/llms.txt", "note": None},
                                  {"url": "https://other.io/llms.txt", "title": "E", "pages": None,
                                   "parent": "https://x.io/llms.txt", "note": "other host, not followed"}])
        lines = summarize_llms(make_llms_plan(SRC_LLMS, tree, []), None)
        self.assertEqual(lines[:5], ["OpenCode: 3 pages: 3 full, 0 stub",
                                     "  Docs: 2   Optional: 1",
                                     "index tree:",
                                     "  llms.txt (1)",
                                     "    _llms/python.txt (2)"])
        self.assertIn("    https://other.io/llms.txt (other host, not followed)", lines)

    def test_summary_added_dropped(self):
        old = make_llms_plan(SRC_LLMS, llms_tree([("a", "Docs"), ("b", "Docs")]), [])
        new = make_llms_plan(SRC_LLMS, llms_tree([("a", "Docs"), ("c", "Docs")]), [], old=old)
        lines = summarize_llms(new, old)
        self.assertTrue(any("added 1" in l and "c" in l for l in lines), lines)
        self.assertTrue(any("dropped 1" in l and "b" in l for l in lines), lines)

    def test_summary_warns_over_300(self):
        tree = llms_tree([("p%d" % i, "Docs") for i in range(301)])
        self.assertTrue(any(l.startswith("warning: 301 full pages") for l in
                            summarize_llms(make_llms_plan(SRC_LLMS, tree, []), None)))


URL = "https://x.io/docs/"


def fake_opener(responses, robots=None):
    """An opener (url) -> (status, bytes): robots.txt gets robots (None: 404),
    every other URL takes the next of responses; .urls records requests."""
    queue = list(responses)

    def opener(url):
        opener.urls.append(url)
        if url.endswith("/robots.txt"):
            return (404, b"") if robots is None else (200, robots.encode())
        return queue.pop(0)
    opener.urls = []
    return opener


def write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class FetchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)

    def test_normalize_source(self):
        for s in ("https://x.io/docs", "https://x.io/docs/", "https://x.io/docs/index.html"):
            self.assertEqual(normalize_source(s), ("https://x.io/docs/", True))
        self.assertEqual(normalize_source(self.tmp), (self.tmp, False))
        self.assertEqual(normalize_source(os.path.join(self.tmp, "index.html")),
                         (self.tmp, False))

    def test_local_folder_reads_pages_and_dir_uris(self):
        write(self.tmp, "api/foo/index.html", "<p>dir page</p>")
        write(self.tmp, "a.html", "<p>file page</p>")
        write(self.tmp, "objects.inv", "inv")
        src = open_source(self.tmp)
        self.assertIn("dir page", src.page("api/foo/"))
        self.assertIn("file page", src.page("a.html"))
        self.assertEqual(src.inventory(), b"inv")
        self.assertIsNone(src.live_url("a.html"))

    def test_local_folder_refuses_escape(self):
        write(os.path.dirname(self.tmp), "secret.html", "s")
        src = open_source(self.tmp)
        with self.assertRaises(build_fetch.FetchError):
            src.page("../secret.html")

    def test_local_base_url_gives_live_urls(self):
        src = open_source(self.tmp, base_url="https://y.org/docs")
        self.assertEqual(src.live_url("a.html"), "https://y.org/docs/a.html")

    def test_retries_then_succeeds(self):
        op = fake_opener([(503, b""), (503, b""), (200, b"<p>ok</p>")])
        sleeps = []
        src = open_source(URL, opener=op, delay=0, sleep=sleeps.append)
        html, errs = fetch_pages(src, ["a.html"])
        self.assertEqual((html, errs), ({"a.html": "<p>ok</p>"}, {}))
        self.assertEqual(sleeps, [1, 2])

    def test_404_becomes_error_not_exception(self):
        src = open_source(URL, opener=fake_opener([(404, b"")]), delay=0, sleep=lambda s: None)
        self.assertEqual(fetch_pages(src, ["a.html"]), ({}, {"a.html": "HTTP 404"}))

    def test_gives_up_after_three_retries(self):
        src = open_source(URL, opener=fake_opener([(500, b"")] * 4), delay=0,
                          sleep=lambda s: None)
        self.assertEqual(fetch_pages(src, ["a.html"])[1], {"a.html": "HTTP 500"})

    def test_robots_disallow(self):
        op = fake_opener([(200, b"<p>b</p>")], robots="User-agent: *\nDisallow: /docs/private/\n")
        src = open_source(URL, opener=op, delay=0)
        html, errs = fetch_pages(src, ["private/a.html", "b.html"])
        self.assertEqual(errs, {"private/a.html": "blocked by robots.txt"})
        self.assertEqual(list(html), ["b.html"])
        self.assertIn("https://x.io/robots.txt", op.urls)

    def test_robots_missing_allows_all(self):
        src = open_source(URL, opener=fake_opener([(200, b"<p>a</p>")]), delay=0)
        self.assertEqual(fetch_pages(src, ["private/a.html"])[1], {})

    def test_inventory_from_url(self):
        op = fake_opener([(200, b"INV")])
        self.assertEqual(open_source(URL, opener=op).inventory(), b"INV")
        self.assertIn("https://x.io/docs/objects.inv", op.urls)
        op = fake_opener([(404, b"")])
        with self.assertRaises(CLIError) as c:
            open_source(URL, opener=op).inventory()
        self.assertEqual(c.exception.code, 4)

    def test_default_opener_sends_user_agent(self):
        seen = {}

        class Resp:
            status = 200
            def read(self): return b"x"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            return Resp()
        with mock.patch.object(build_fetch._URL_OPENER, "open", fake_urlopen):
            self.assertEqual(build_fetch.default_opener("https://x.io/a.html"), (200, b"x"))
        self.assertEqual(seen["ua"], "docshelf-build/" + build_core.VERSION)

    def test_default_opener_refuses_other_schemes(self):
        with self.assertRaises(ValueError):
            build_fetch.default_opener("file:///etc/passwd")


SPHINX_PAGE = """<!DOCTYPE html><html><head><title>opt</title>
<style>body{color:red}</style><script>var x = "<p>Script text</p>";</script></head>
<body><nav class="wy-nav-side"><p>Sidebar</p><a href="index.html">Home</a></nav>
<div class="wy-nav-content"><div role="main" class="document">
<section id="opt"><h1>opt<a class="headerlink" href="#opt" title="Link">\u00b6</a></h1>
<p>Real text &amp; more, <code>a&lt;b</code>.</p><img src="x.png" alt="A diagram"><br>
</section></div><footer><p>Footer</p></footer></div></body></html>"""

HTML_WITH_LINKS = """<p><a href="../using/x.html#sec">x</a> <a href="../api/foo/">foo</a>
<a href="#local">here</a> <a href="https://other.org/p">other</a>
<a href="../missing.html">missing</a> <a href="opt.html#flag">self</a>
<a href="mailto:a@example.org">mail</a></p>"""


class HtmlTests(unittest.TestCase):
    def test_main_content_drops_chrome(self):
        out = main_content(SPHINX_PAGE)
        for gone in ("Sidebar", "Footer", "<script", "<style", "Script text", "headerlink",
                     "\u00b6", "<nav"):
            self.assertNotIn(gone, out)
        self.assertIn("Real text &amp; more", out)
        self.assertIn("<code>a&lt;b</code>", out)
        self.assertIn('<section id="opt">', out)

    def test_img_becomes_alt_text(self):
        out = main_content(SPHINX_PAGE)
        self.assertNotIn("<img", out)
        self.assertIn("A diagram", out)

    def test_main_content_fallbacks(self):
        self.assertIn("T", main_content("<html><body><nav>N</nav><main><p>T</p></main></body></html>"))
        self.assertNotIn("N", main_content("<html><body><nav>N</nav><main><p>T</p></main></body></html>"))
        self.assertIn("B", main_content('<div class="sphinxsidebar">S</div><div class="body">B</div>'))
        self.assertIn("Only", main_content("<html><body><p>Only</p></body></html>"))

    def test_rewrite_links(self):
        keys = {"cmd/opt.html": "cmd/opt", "using/x.html": "using/x", "api/foo/": "api/foo"}
        out = rewrite_links(HTML_WITH_LINKS, "cmd/opt", "cmd/opt.html", keys, "https://x.io/docs/")
        self.assertIn('href="../using/x#sec"', out)
        self.assertIn('href="../api/foo"', out)
        self.assertIn('href="#local"', out)
        self.assertIn('href="https://other.org/p"', out)
        self.assertIn('href="https://x.io/docs/missing.html"', out)
        self.assertIn('href="opt#flag"', out)
        self.assertIn('href="mailto:a@example.org"', out)

    def test_rewrite_links_from_dir_style_and_top_pages(self):
        keys = {"api/foo/": "api/foo", "api/bar/": "api/bar", "index.html": "index"}
        out = rewrite_links('<a href="../bar/#b">b</a><a href="../../">home</a>',
                            "api/foo", "api/foo/", keys, None)
        self.assertIn('href="bar#b"', out)
        self.assertIn('href="../index"', out)
        out = rewrite_links('<a href="api/foo/">f</a>', "index", "index.html", keys, None)
        self.assertIn('href="api/foo"', out)

    def test_rewrite_links_no_live_base_keeps_unknown(self):
        out = rewrite_links('<a href="../missing.html">m</a>', "cmd/opt", "cmd/opt.html", {}, None)
        self.assertIn('href="../missing.html"', out)

    def test_ids_and_fragments_with_spaces(self):
        # real Yosys: <dt id="opt_clean.opt_clean [options] [selection]">
        out = main_content('<main><dt id="a.b [options]">x</dt><a href="#a.b [options]">l</a></main>')
        self.assertIn('id="a.b_[options]"', out)
        out = rewrite_links(out, "cmd/opt", "cmd/opt.html", {}, None)
        self.assertIn('href="#a.b_[options]"', out)
        keys = {"cmd/x.html": "cmd/x"}
        out = rewrite_links('<a href="x.html#p q">x</a>', "cmd/opt", "cmd/opt.html", keys, None)
        self.assertIn('href="x#p_q"', out)

    def test_stub_html(self):
        h = stub_html("Install", "Getting started", None, "https://x.io/docs/i.html", None)
        self.assertIn("<h1>Install</h1>", h)
        self.assertIn("Getting started", h)
        self.assertIn("Not stored; read it at", h)
        self.assertIn('href="https://x.io/docs/i.html"', h)
        h = stub_html("A", None, "Tutorial about A.", None,
                      "left out of the build (source: guide/a.html)")
        self.assertIn("left out of the build", h)
        self.assertIn("Tutorial about A.", h)
        h = stub_html("B", None, None, "https://x.io/b.html", "HTTP 404")
        self.assertIn("Not stored (HTTP 404); read it at", h)
        self.assertIn("&lt;", stub_html("<x>", None, None, None, "n"))


DOCVOL_HTML = {"cmd/opt.html": "<html><body><nav>N</nav><div role='main'><h1 id='opt'>opt</h1>"
                               "<a href='../guide/a.html#sec'>guide</a></div></body></html>",
               "index.html": "<div role='main'><p>Home</p></div>"}


def load(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return json.load(f)


class DocvolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = os.path.realpath(tmp.name)
        self.plan = make_plan(SRC, "abc", HDR, ENTRIES, [("full", "index")])
        self.folder = os.path.join(self.cache, "built", "demo")

    def write(self, html=None, errors=None, now=1800000000):
        return write_docvol(self.cache, "demo", self.plan, ENTRIES,
                            DOCVOL_HTML if html is None else html, errors or {}, now=now)

    def test_derive_name(self):
        self.assertEqual(derive_name({"project": "YosysHQ Yosys", "version": ""}), "yosyshq-yosys")
        self.assertEqual(derive_name({"project": "SpinalHDL", "version": "master"}),
                         "spinalhdl~master")
        self.assertEqual(derive_name({"project": "", "version": ""}), "docs")

    def test_check_name(self):
        make_manifest = os.path.join(self.cache, "devdocs")
        os.makedirs(make_manifest)
        with open(os.path.join(make_manifest, "docs.json"), "w") as f:
            json.dump([{"slug": "python~3.12"}], f)
        with self.assertRaises(CLIError) as c:
            check_name(self.cache, "python~3.12")
        self.assertEqual(c.exception.code, 2)
        self.assertIn("docshelf install python~3.12", str(c.exception))
        os.makedirs(os.path.join(make_manifest, "lua~5.4"))
        with self.assertRaises(CLIError):
            check_name(self.cache, "lua~5.4")
        for bad in ("../x", "a/b", "", "-x"):
            with self.assertRaises(CLIError):
                check_name(self.cache, bad)
        check_name(self.cache, "yosys")

    def test_role_labels(self):
        self.assertEqual([role_label(r) for r in ("py:function", "cmd:cmd", "std:doc",
                                                  "std:label", "std:term")],
                         ["function", "cmd", "Page", "Section", "Term"])

    def test_write_docvol_shape(self):
        meta = self.write()
        idx, db = load(self.folder, "index.json"), load(self.folder, "db.json")
        self.assertIn({"name": "opt", "type": "cmd", "path": "cmd/opt#opt"}, idx["entries"])
        self.assertIn({"name": "opt - optimize", "type": "Page", "path": "cmd/opt"},
                      idx["entries"])
        self.assertIn({"name": "Guide A", "type": "Guide", "path": "guide/a"}, idx["entries"])
        self.assertFalse(any(e["path"].startswith("guide/a#") for e in idx["entries"]))
        self.assertIn({"name": "cmd", "count": 1, "slug": "cmd"}, idx["types"])
        self.assertIn("Not stored; read it at", db["guide/a"])
        self.assertIn('href="https://x.io/docs/guide/a.html"', db["guide/a"])
        self.assertIn('href="../guide/a#sec"', db["cmd/opt"])
        self.assertNotIn("<nav", db["cmd/opt"])
        self.assertEqual(meta, load(self.folder, "meta.json"))
        self.assertEqual(meta["mtime"], 1800000000)
        self.assertEqual(meta["origin"], "docshelf-build")
        self.assertEqual(meta["format"], build_core.DOCVOL_FORMAT)
        self.assertEqual(build_core.DOCVOL_FORMAT, 1)
        self.assertEqual(meta["slug"], "demo")
        self.assertEqual(meta["source"], SRC)
        self.assertEqual(meta["inventory_sha256"], "abc")
        self.assertEqual(meta["entry_count"], len(idx["entries"]))
        self.assertEqual(sorted(os.listdir(self.folder)), ["db.json", "index.json", "meta.json"])

    def test_entry_anchor_with_spaces(self):
        entries = ENTRIES + inv(("opt.opt [options]", "cmd:cmdusage", "cmd/opt.html#opt.opt [options]",
                                 "[options]"))
        write_docvol(self.cache, "demo", self.plan, entries, DOCVOL_HTML, {}, now=1)
        paths = [e["path"] for e in load(self.folder, "index.json")["entries"]]
        self.assertIn("cmd/opt#opt.opt_[options]", paths)

    def test_std_label_with_dash_dispname_skipped(self):
        entries = ENTRIES + inv(("anon", "std:label", "cmd/opt.html#anon", "-"))
        write_docvol(self.cache, "demo", self.plan, entries, DOCVOL_HTML, {}, now=1)
        self.assertFalse(any(e["name"] == "anon" for e in load(self.folder, "index.json")["entries"]))

    def test_local_source_without_base_url_stub(self):
        with tempfile.TemporaryDirectory() as d:
            self.plan = make_plan(d, "abc", HDR, ENTRIES, [("full", "index")])
            self.write()
        self.assertIn("left out of the build (source: guide/a.html)",
                      load(self.folder, "db.json")["guide/a"])

    def test_failed_page_becomes_stub(self):
        self.write(html={"index.html": "<p>i</p>"}, errors={"cmd/opt.html": "HTTP 404"})
        db = load(self.folder, "db.json")
        self.assertIn("Not stored (HTTP 404); read it at", db["cmd/opt"])
        names = [e["name"] for e in load(self.folder, "index.json")["entries"]]
        self.assertIn("opt", names)

    def test_failed_write_keeps_previous(self):
        self.write(now=1)
        before = {n: load(self.folder, n) for n in ("index.json", "db.json", "meta.json")}
        real = os.replace
        calls = []

        def flaky(a, b):
            calls.append(b)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(a, b)
        with mock.patch("os.replace", flaky):
            with self.assertRaises(CLIError):
                self.write(html={"cmd/opt.html": "<p>new</p>", "index.html": "<p>new</p>"},
                           now=2)
        for n, data in before.items():
            self.assertEqual(load(self.folder, n), data, n)
        self.assertEqual(sorted(os.listdir(self.folder)), ["db.json", "index.json", "meta.json"])

    def test_partial_failure_keeps_previous_page(self):
        self.write(now=1)
        good = load(self.folder, "db.json")["cmd/opt"]
        meta = self.write(html={"index.html": "<p>i</p>"}, errors={"cmd/opt.html": "HTTP 503"},
                          now=2)
        self.assertEqual(load(self.folder, "db.json")["cmd/opt"], good)
        self.assertEqual(meta["reused"], ["cmd/opt.html"])

    def test_partial_failure_without_previous_copy_is_stub(self):
        self.write(html={"index.html": "<p>i</p>"}, errors={"cmd/opt.html": "HTTP 503"}, now=1)
        meta = self.write(html={"index.html": "<p>i</p>"}, errors={"cmd/opt.html": "HTTP 503"},
                          now=2)
        self.assertIn("HTTP 503", load(self.folder, "db.json")["cmd/opt"])
        self.assertEqual(meta["reused"], [])

    def test_failed_first_write_leaves_nothing(self):
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(CLIError):
                self.write()
        self.assertFalse(os.path.exists(self.folder))


class LlmsDocvolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.plan = make_llms_plan(
            SRC_LLMS, llms_tree([("docs/a", "Docs"), ("docs/b", "Docs"), ("pricing", None)]), [])
        self.plan["pages"]["pricing"]["keep"] = "stub"
        self.folder = os.path.join(self.cache, "built", "demo")
        self.raw = {"docs/a": ("# A\n\n## Usage\n\nSee [b](b.md).\n", "md"),
                    "docs/b": ("<html><nav>n</nav><main><h2 id='k'>K</h2></main></html>", "html")}

    def test_links_rewritten(self):
        keys = {"https://x.io/docs/a.md": "docs/a", "https://x.io/docs/b.md": "docs/b"}
        html = ('<a href="b.md#x y">b</a><a href="/docs/b">b2</a><a href="/blog/">blog</a>'
                '<a href="https://e.x/">e</a><a href="#Top">t</a>')
        self.assertEqual(rewrite_url_links(html, "docs/a", "https://x.io/docs/a.md", keys, "x.io"),
                         '<a href="b#x_y">b</a><a href="b">b2</a><a href="https://x.io/blog/">blog</a>'
                         '<a href="https://e.x/">e</a><a href="#Top">t</a>')

    def test_headings(self):
        self.assertEqual(headings('<h1 id="t">T</h1><h2 id="a">A <code>x</code></h2>'
                                  '<h3>no id</h3><h3 id="b">B</h3>'),
                         [(2, "a", "A x"), (3, "b", "B")])

    def test_write_llms_docvol(self):
        write_llms_docvol(self.cache, "demo", self.plan, self.raw, {}, now=0)
        index, db, meta = (load(self.folder, f) for f in ("index.json", "db.json", "meta.json"))
        self.assertEqual(meta["source_kind"], "llms")
        self.assertEqual(meta["format"], 1)
        self.assertEqual(meta["index_sha256"], "s1")
        self.assertNotIn("inventory_sha256", meta)
        self.assertIn({"name": "Usage", "type": "Docs", "path": "docs/a#usage"}, index["entries"])
        self.assertIn({"name": "K", "type": "Docs", "path": "docs/b#k"}, index["entries"])
        self.assertIn({"name": "PRICING", "type": "Pages", "path": "pricing"}, index["entries"])
        self.assertIn('href="b"', db["docs/a"])
        self.assertNotIn("<nav>", db["docs/b"])
        self.assertIn("https://x.io/pricing.md", db["pricing"])

    def test_failed_page_keeps_previous_copy(self):
        write_llms_docvol(self.cache, "demo", self.plan, self.raw, {}, now=0)
        before = load(self.folder, "db.json")["docs/a"]
        raw = {k: v for k, v in self.raw.items() if k != "docs/a"}
        meta = write_llms_docvol(self.cache, "demo", self.plan, raw, {"docs/a": "HTTP 500"}, now=1)
        self.assertEqual(load(self.folder, "db.json")["docs/a"], before)
        self.assertEqual(meta["reused"], ["docs/a"])
        shutil.rmtree(self.folder)
        meta = write_llms_docvol(self.cache, "demo", self.plan, raw, {"docs/a": "HTTP 500"}, now=2)
        stub = load(self.folder, "db.json")["docs/a"]
        self.assertIn("HTTP 500", stub)
        self.assertIn("https://x.io/docs/a.md", stub)
        self.assertEqual(meta["reused"], [])

    def test_docshelf_reads_llms_docvol(self):
        if not docshelf_reads_built():
            self.skipTest("docshelf without BuiltDocvol")
        write_llms_docvol(self.cache, "demo", self.plan, self.raw, {}, now=0)
        env = dict(os.environ, HOME=self.tmp, DOCSHELF_CACHE_DIR=self.cache,
                   DOCSHELF_NOTES_DIR=os.path.join(self.tmp, "notes"))
        r = subprocess.run([sys.executable, DOCSHELF, "search", "Usage", "-d", "demo"],
                           capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("docs/a#usage", r.stdout)


def docshelf_reads_built() -> bool:
    with open(os.path.join(os.path.dirname(DOCSHELF), "shelf_devdocs.py"), encoding="utf-8") as f:
        return "class BuiltDocvol" in f.read()


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        self.site = os.path.join(self.tmp, "site")
        rows = [(e.name, e.role, "1", e.uri, e.dispname) for e in ENTRIES]
        os.makedirs(self.site)
        with open(os.path.join(self.site, "objects.inv"), "wb") as f:
            f.write(make_inv(rows))
        write(self.site, "cmd/opt.html", DOCVOL_HTML["cmd/opt.html"])
        write(self.site, "index.html", DOCVOL_HTML["index.html"])
        for p in ("guide/index.html", "guide/a.html", "guide/b.html"):
            write(self.site, p, "<div role='main'><p>Guide text %s</p></div>" % p)
        self.plan_path = os.path.join(self.cache, "built-plans", "demo.json")
        self.docvol = os.path.join(self.cache, "built", "demo")

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env)
        return code, out.getvalue(), err.getvalue()

    def run_docshelf(self, *args):
        env = dict(os.environ, **self.env)
        return subprocess.run([sys.executable, DOCSHELF, *args], capture_output=True,
                              text=True, env=env, cwd=self.tmp)

    def test_plan_then_build(self):
        code, out, err = self.run_main("plan", self.site, "--name", "demo")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(self.plan_path))
        self.assertIn("1 full, 4 stub", out)
        self.assertFalse(os.path.exists(self.docvol))
        code, out, err = self.run_main("build", "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("built demo", out)
        db = load(self.docvol, "db.json")
        self.assertIn("left out of the build", db["guide/a"])
        self.assertIn("opt", db["cmd/opt"])

    def test_docshelf_reads_the_build(self):
        if not docshelf_reads_built():
            self.skipTest("docshelf without BuiltDocvol (update/docshelf not merged yet)")
        self.run_main("build", self.site, "--name", "demo")
        r = self.run_docshelf("search", "opt", "-d", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("demo:cmd/opt#opt", r.stdout)
        r = self.run_docshelf("show", "demo:guide/a")
        self.assertIn("left out of the build", r.stdout)

    def test_build_source_in_one_step_and_rebuild(self):
        code, _, err = self.run_main("build", self.site, "--name", "demo", "--full", "guide/*")
        self.assertEqual(code, 0, err)
        self.assertIn("Guide text guide/a.html", load(self.docvol, "db.json")["guide/a"])
        first = load(self.docvol, "meta.json")["mtime"]
        with mock.patch("time.time", return_value=first + 100):
            code, _, err = self.run_main("build", "demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(load(self.docvol, "meta.json")["mtime"], first + 100)
        self.assertEqual(load_plan(self.plan_path)["overrides"], [["full", "guide/*"]])

    def test_override_order_is_kept(self):
        self.run_main("plan", self.site, "--name", "demo", "--full", "guide/*",
                      "--stub", "guide/a")
        p = load_plan(self.plan_path)
        self.assertEqual(p["overrides"], [["full", "guide/*"], ["stub", "guide/a"]])
        self.assertEqual(p["pages"]["guide/a"]["keep"], "stub")

    def test_all_and_reset_flags(self):
        self.run_main("plan", self.site, "--name", "demo", "--all")
        self.assertEqual(load_plan(self.plan_path)["overrides"], [["full", "*"]])
        self.run_main("plan", self.site, "--name", "demo", "--reset")
        self.assertEqual(load_plan(self.plan_path)["overrides"], [])

    def test_derived_name(self):
        code, out, err = self.run_main("plan", self.site)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(self.cache, "built-plans", "demo~1.0.json")))

    def test_rebuild_when_every_page_fails_keeps_previous(self):
        self.assertEqual(self.run_main("build", self.site, "--name", "demo")[0], 0)
        before = load(self.docvol, "db.json")
        os.remove(os.path.join(self.site, "cmd", "opt.html"))
        os.remove(os.path.join(self.site, "index.html"))
        self.run_main("plan", self.site, "--name", "demo", "--full", "index")
        code, out, err = self.run_main("build", "demo")
        self.assertEqual(code, 4, out + err)
        self.assertIn("every page", err)
        self.assertEqual(load(self.docvol, "db.json"), before)

    def test_failed_pages_warn_on_stderr(self):
        os.remove(os.path.join(self.site, "index.html"))
        code, out, err = self.run_main("build", self.site, "--name", "demo", "--full", "index")
        self.assertEqual(code, 0, err)
        self.assertIn("1 page failed", err)

    def test_build_without_plan(self):
        code, _, err = self.run_main("build", "nothing")
        self.assertEqual(code, 2)
        self.assertIn("plan", err)

    def test_bad_inventory_exit_3(self):
        with open(os.path.join(self.site, "objects.inv"), "wb") as f:
            f.write(b"<html>404</html>")
        self.assertEqual(self.run_main("plan", self.site, "--name", "demo")[0], 3)

    def test_list_and_remove(self):
        self.run_main("build", self.site, "--name", "demo")
        code, out, _ = self.run_main("list")
        self.assertEqual(code, 0)
        self.assertIn("demo", out)
        self.assertIn(self.site, out)
        code, out, _ = self.run_main("remove", "demo")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(self.plan_path))
        self.assertFalse(os.path.isdir(self.docvol))
        code, out, _ = self.run_main("list")
        self.assertIn("not built", out)
        self.assertEqual(self.run_main("remove", "demo", "--plan")[0], 0)
        self.assertFalse(os.path.isfile(self.plan_path))
        self.assertEqual(self.run_main("remove", "demo")[0], 2)

    def test_version(self):
        code, out, _ = self.run_main("--version")
        self.assertEqual(code, 0)
        self.assertIn(build_core.VERSION, out)

    def test_script_runs(self):
        r = subprocess.run([sys.executable, os.path.join(SKILL, "scripts", "docshelf_build.py"),
                            "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("plan", r.stdout)


FLAT_INDEX = """\ufeff# OpenCode\r
\r
> Agents in your terminal.\r
\r
- [Home](https://x.io/index.md)\r
\r
## Docs\r
\r
- [Build](https://x.io/docs/build.md): build agents\r
* [Run](/docs/run/)\r
  - [Run flags](docs/run/flags.mdx)\r
\r
## Optional\r
\r
- [Pricing](https://x.io/pricing)\r
- [Build again](https://x.io/docs/build.md)\r
"""


OC_INDEX = ("# OpenCode\n## Docs\n- [Build](https://x.io/docs/build.md): build agents\n"
            "- [Run](https://x.io/docs/run)\n## Optional\n- [Pricing](https://x.io/pricing.md)\n")
BUILD_MD = ("---\ntitle: Build\n---\nimport X from 'x'\n# Build\n\n<Note>Read [run](/docs/run).</Note>"
            "\n\n## Options\n\n```bash\nopencode run\n--model NAME\n```\n")
# signature_lines == 1 (the "--model" line)


class LlmsCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache}
        self.site = {
            "https://x.io/llms.txt": (200, OC_INDEX.encode()),
            "https://x.io/docs/build.md": (200, BUILD_MD.encode()),
            "https://x.io/docs/run": (200, b"<!doctype html><html><body>shell</body></html>"),
            "https://x.io/docs/run.md": (200, b"# Run\n\nRun it.\n"),
            "https://x.io/pricing.md": (200, b"# Pricing\n\nFree.\n"),
        }
        self.urls = []
        self.plan_path = os.path.join(self.cache, "built-plans", "opencode.json")
        self.docvol = os.path.join(self.cache, "built", "opencode")

    def opener(self, url):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return 404, b""
        return self.site.get(url, (404, b""))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env, opener=self.opener,
                                       sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def fetched_urls(self):
        return [u for u in self.urls if not u.endswith("robots.txt")]

    def test_plan_then_build_then_warm_rebuild(self):
        code, out, _ = self.run_main("plan", "https://x.io/llms.txt")
        self.assertEqual(code, 0)
        self.assertIn("OpenCode: 3 pages: 3 full, 0 stub", out)
        self.assertIn("  llms.txt (3)", out)
        code, out, _ = self.run_main("build", "opencode")
        self.assertEqual(code, 0, out)
        self.assertIn("built opencode: 3 full, 0 stub, 0 failed", out)
        plan = load_plan(self.plan_path)
        self.assertEqual(plan["pages"]["docs/build"]["signals"]["signature_lines"], 1)
        self.assertIn("fetched", plan["pages"]["docs/run"])
        self.assertTrue(os.path.isfile(os.path.join(self.cache, "built-src", "opencode",
                                                    "docs", "run.md")))
        self.urls.clear()
        self.assertEqual(self.run_main("build", "opencode")[0], 0)
        self.assertEqual(self.fetched_urls(), ["https://x.io/llms.txt"])

    def test_build_from_source_in_one_step(self):
        code, out, _ = self.run_main("build", "https://x.io/llms.txt")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.docvol, "db.json")))

    def test_front_matter_fills_empty_description(self):
        self.run_main("build", "https://x.io/llms.txt")
        plan = load_plan(self.plan_path)
        self.assertEqual(plan["pages"]["docs/build"]["description"], "build agents")
        self.site["https://x.io/llms.txt"] = (
            200, b"# OpenCode\n## Docs\n- [Build](https://x.io/docs/build.md)\n")
        self.site["https://x.io/docs/build.md"] = (
            200, b"---\ntitle: Build\ndescription: from front matter\n---\n# Build\n")
        self.run_main("plan", "https://x.io/llms.txt", "--reset")
        self.run_main("build", "opencode", "--refetch")
        self.assertEqual(load_plan(self.plan_path)["pages"]["docs/build"]["description"],
                         "from front matter")

    def test_md_retry_through_cli(self):
        self.run_main("build", "https://x.io/llms.txt")
        self.assertIn("https://x.io/docs/run.md", self.urls)
        cached = os.path.join(self.cache, "built-src", "opencode", "docs", "run.md")
        with open(cached, encoding="utf-8") as f:
            self.assertIn("Run it.", f.read())
        self.assertFalse(os.path.exists(cached[:-3] + ".html"))

    def test_index_change_replans(self):
        self.run_main("build", "https://x.io/llms.txt")
        self.site["https://x.io/llms.txt"] = (
            200, (OC_INDEX + "- [New](https://x.io/docs/new.md)\n").encode())
        self.site["https://x.io/docs/new.md"] = (200, b"# New\n\nNew page.\n")
        code, out, _ = self.run_main("build", "opencode")
        self.assertEqual(code, 0, out)
        self.assertIn("the index changed", out)
        self.assertIn("added 1 page: docs/new", out)
        self.assertIn("docs/new", load_plan(self.plan_path)["pages"])

    def test_subindex_source_same_keys(self):
        self.site["https://x.io/llms.txt"] = (
            200, b"# OpenCode\n## Docs\n- [Build](https://x.io/docs/build.md)\n"
                 b"- [Python](https://x.io/_llms/py.txt)\n")
        self.site["https://x.io/_llms/py.txt"] = (
            200, b"# Python\n## API\n- [Build](https://x.io/docs/build.md)\n"
                 b"- [Client](https://x.io/py/client.md)\n")
        self.assertEqual(self.run_main("plan", "https://x.io/llms.txt")[0], 0)
        code, _, err = self.run_main("plan", "https://x.io/_llms/py.txt", "--name", "py")
        self.assertEqual(code, 0, err)
        root = load_plan(self.plan_path)["pages"]
        sub = load_plan(os.path.join(self.cache, "built-plans", "py.json"))["pages"]
        self.assertEqual(set(root), {"docs/build", "py/client"})
        self.assertEqual(set(sub), {"docs/build", "py/client"})

    def test_failed_page_records_error_keeps_copy(self):
        self.run_main("build", "https://x.io/llms.txt")
        self.site["https://x.io/docs/run.md"] = (500, b"")
        self.site["https://x.io/docs/run"] = (500, b"")
        code, out, _ = self.run_main("build", "opencode", "--refetch")
        self.assertEqual(code, 0, out)
        self.assertEqual(load_plan(self.plan_path)["pages"]["docs/run"]["fetch_error"], "HTTP 500")
        self.assertIn("1 failed", out)
        self.assertIn("Run it.", load(self.docvol, "db.json")["docs/run"])

    def test_base_url_rejected(self):
        code, _, err = self.run_main("plan", "https://x.io/llms.txt", "--base-url", "https://x.io/")
        self.assertEqual(code, 2)
        self.assertIn("--base-url", err)

    def test_not_an_index(self):
        self.site["https://x.io/llms.txt"] = (200, b"<!doctype html><html><body>nope</body></html>")
        code, _, err = self.run_main("plan", "https://x.io/llms.txt")
        self.assertEqual(code, 3, err)
        self.assertFalse(os.path.exists(self.plan_path))

    def test_remove_deletes_page_cache(self):
        self.run_main("build", "https://x.io/llms.txt")
        pages = os.path.join(self.cache, "built-src", "opencode")
        self.assertTrue(os.path.isdir(pages))
        code, out, _ = self.run_main("remove", "opencode")
        self.assertEqual(code, 0)
        self.assertIn("page cache", out)
        self.assertFalse(os.path.exists(pages))
        self.assertFalse(os.path.exists(self.docvol))
        self.assertTrue(os.path.isfile(self.plan_path))

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(docshelf_build.main(["--version"]), 0)
        self.assertIn(build_core.VERSION, out.getvalue())
        skill = os.path.join(SKILL, "SKILL.md")
        with open(skill, encoding="utf-8") as f:
            self.assertIn('version: "%s"' % build_core.VERSION, f.read())


class LlmsIndexTests(unittest.TestCase):
    def test_parse_flat_index(self):
        title, links = parse_index(FLAT_INDEX, "https://x.io/llms.txt")
        self.assertEqual(title, "OpenCode")
        self.assertEqual([(l.title, l.url, l.note, l.section) for l in links], [
            ("Home", "https://x.io/index.md", None, None),
            ("Build", "https://x.io/docs/build.md", "build agents", "Docs"),
            ("Run", "https://x.io/docs/run/", None, "Docs"),
            ("Run flags", "https://x.io/docs/run/flags.mdx", None, "Docs"),
            ("Pricing", "https://x.io/pricing", None, "Optional"),
            ("Build again", "https://x.io/docs/build.md", None, "Optional")])

    def test_url_key(self):
        h = "x.io"
        for url, key in [("https://x.io/docs/build.md", "docs/build"),
                         ("https://x.io/docs/run/", "docs/run/index"),
                         ("https://x.io/", "index"),
                         ("https://x.io/a/b.mdx?x=1#frag", "a/b"),
                         ("https://x.io/a/page.html", "a/page"),
                         ("https://other.io/docs/a.md", "other.io/docs/a"),
                         ("https://x.io/../../etc/passwd.md", "etc/passwd"),
                         ("https://x.io/a/%2e%2e/%2e%2e/b.md", "b"),
                         ("https://x.io//a//b.md", "a/b")]:
            self.assertEqual(url_key(url, h), key, url)

    def test_is_llms_source(self):
        self.assertTrue(is_llms_source("https://x.io/llms.txt"))
        self.assertTrue(is_llms_source("https://x.io/_llms/python.txt"))
        self.assertFalse(is_llms_source("https://x.io/docs/"))
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "llms.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("# T\n")
            self.assertTrue(is_llms_source(f))
            self.assertFalse(is_llms_source(d))
            self.assertFalse(is_llms_source(os.path.join(d, "missing.txt")))

    def test_tree_flat(self):
        tree = read_tree("https://x.io/llms.txt", get_text={"https://x.io/llms.txt": FLAT_INDEX}.__getitem__)
        self.assertEqual(tree.title, "OpenCode")
        self.assertEqual(tree.main_host, "x.io")
        self.assertEqual([p.key for p in tree.pages],
                         ["index", "docs/build", "docs/run/index", "docs/run/flags", "pricing"])
        self.assertEqual(tree.pages[1].description, "build agents")
        self.assertEqual(tree.indexes, [{"url": "https://x.io/llms.txt", "title": "OpenCode",
                                         "pages": 5, "parent": None, "note": None}])
        self.assertEqual(tree.sha256, hashlib.sha256(FLAT_INDEX.encode()).hexdigest())

    def test_tree_nested_cycle_dup_other_host(self):
        texts = {
            "https://x.io/llms.txt": "# Root\n## Python\n- [Py](/_llms/python.txt)\n"
                                     "- [Ext](https://other.io/llms.txt)\n- [Top](/top.md)\n",
            "https://x.io/_llms/python.txt": "# Python docs\n- [A](/py/a.md)\n- [Top](/top.md)\n"
                                             "- [Back](/llms.txt)\n- [Deeper](/_llms/d1.txt)\n",
            "https://x.io/_llms/d1.txt": "# D1\n- [D](/d/1.md)\n- [D2](/_llms/d2.txt)\n",
            "https://x.io/_llms/d2.txt": "# D2\n- [E](/d/2.md)\n- [D3](/_llms/d3.txt)\n",
        }
        tree = read_tree("https://x.io/llms.txt", texts.__getitem__)
        self.assertEqual([(p.key, p.section) for p in tree.pages],
                         [("py/a", "Python / Python docs"), ("top", "Python / Python docs"),
                          ("d/1", "Python / Python docs / D1"), ("d/2", "Python / Python docs / D1 / D2")])
        notes = {i["url"]: i["note"] for i in tree.indexes}
        self.assertEqual(notes["https://other.io/llms.txt"], "other host, not followed")
        self.assertEqual(notes["https://x.io/_llms/d3.txt"], "depth limit")
        self.assertEqual(sum(1 for i in tree.indexes if i["url"] == "https://x.io/llms.txt"), 1)

    def test_tree_local_file_main_host_by_majority(self):
        text = ("# Local\n- [A](https://x.io/a.md)\n- [O](https://other.io/o.md)\n"
                "- [B](https://x.io/b.md)\n")
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "llms.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(text)
            tree = read_tree(f, get_text=lambda u: self.fail("no fetch expected: " + u))
        self.assertEqual(tree.main_host, "x.io")
        self.assertEqual([p.key for p in tree.pages], ["a", "other.io/o", "b"])
        self.assertEqual(tree.indexes[0]["url"], f)

    def test_tree_same_key_is_same_page(self):
        text = ("# T\n- [A](https://x.io/docs/build.md)\n"
                "- [B](https://x.io/docs/build.mdx)\n- [C](https://x.io/docs/build)\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            tree = read_tree("https://x.io/llms.txt", {"https://x.io/llms.txt": text}.__getitem__)
        self.assertEqual([p.key for p in tree.pages], ["docs/build"])
        self.assertEqual(tree.pages[0].url, "https://x.io/docs/build.md")
        self.assertEqual(tree.pages[0].title, "A")
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(tree.indexes[0]["pages"], 1)

    def test_tree_skips_full_text_index(self):
        root = ("# T\n- [Full site](https://x.io/llms-full.txt)\n"
                "- [Docs](https://x.io/docs/llms.txt)\n")
        docs = "# Docs\n- [A](https://x.io/docs/a.md)\n"
        texts = {"https://x.io/llms.txt": root, "https://x.io/docs/llms.txt": docs}
        tree = read_tree("https://x.io/llms.txt", texts.__getitem__)
        self.assertEqual([p.key for p in tree.pages], ["docs/a"])
        full = [i for i in tree.indexes if i["url"] == "https://x.io/llms-full.txt"][0]
        self.assertEqual(full, {"url": "https://x.io/llms-full.txt", "title": "Full site",
                                "pages": None, "parent": "https://x.io/llms.txt",
                                "note": "full text, not followed"})

    def test_tree_subindex_failure_not_fatal(self):
        root = "# T\n- [A](https://x.io/a.md)\n- [Sub](https://x.io/sub/llms.txt)\n"

        def get(url):
            if url == "https://x.io/llms.txt":
                return root
            raise CLIError("cannot fetch %s: HTTP 404" % url, 4)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            tree = read_tree("https://x.io/llms.txt", get)
        self.assertEqual([p.key for p in tree.pages], ["a"])
        sub = [i for i in tree.indexes if i["url"] == "https://x.io/sub/llms.txt"][0]
        self.assertIsNone(sub["pages"])
        self.assertIn("fetch failed", sub["note"])
        self.assertIn("HTTP 404", sub["note"])
        self.assertIn("sub/llms.txt", err.getvalue())

    def test_tree_root_failure_still_raises(self):
        def get(url):
            raise CLIError("cannot fetch " + url, 4)
        with self.assertRaises(CLIError):
            read_tree("https://x.io/llms.txt", get)

    def test_tree_dedup_ignores_fragment(self):
        text = "# T\n- [A](https://x.io/a.md#one)\n- [A2](https://x.io/a.md#two)\n"
        tree = read_tree("https://x.io/llms.txt", {"https://x.io/llms.txt": text}.__getitem__)
        self.assertEqual([p.url for p in tree.pages], ["https://x.io/a.md#one"])

    def test_tree_without_links_is_error(self):
        with self.assertRaises(CLIError) as cm:
            read_tree("https://x.io/llms.txt", lambda u: "<!doctype html><html><body>Not found</body></html>")
        self.assertEqual(cm.exception.code, 3)


class LlmsFetchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = PageCache(os.path.join(tmp.name, "built-src", "demo"))

    def test_md_retry_when_html(self):
        op = fake_opener([(200, b"<!DOCTYPE html><html>x</html>"), (200, b"# Real")])
        src = open_url_source(opener=op, sleep=lambda s: None)
        self.assertEqual(fetch_llms_page(src, "https://x.io/docs/a"), ("# Real", "md"))
        self.assertEqual(op.urls[-1], "https://x.io/docs/a.md")

    def test_md_retry_fails_keeps_html(self):
        op = fake_opener([(200, b"  <html><main><p>x</p></main></html>"), (404, b"")])
        text, kind = fetch_llms_page(open_url_source(opener=op, sleep=lambda s: None),
                                     "https://x.io/docs/a/")
        self.assertEqual(kind, "html")
        self.assertEqual(op.urls[-1], "https://x.io/docs/a.md")

    def test_no_retry_for_md_url(self):
        op = fake_opener([(200, b"<html>odd</html>")])
        self.assertEqual(fetch_llms_page(open_url_source(opener=op, sleep=lambda s: None),
                                         "https://x.io/a.md")[1], "html")
        self.assertEqual(len([u for u in op.urls if not u.endswith("robots.txt")]), 1)

    def test_looks_html(self):
        self.assertTrue(looks_html("\n  <!DocType html>"))
        self.assertTrue(looks_html("<HTML>"))
        self.assertFalse(looks_html("# Title\n<html> later"))

    def test_robots_per_host(self):
        seen = []

        def opener(url):
            seen.append(url)
            if url == "https://x.io/robots.txt":
                return 200, b"User-agent: *\nDisallow: /private\n"
            if url.endswith("/robots.txt"):
                return 404, b""
            return 200, b"# ok"
        src = open_url_source(opener=opener, sleep=lambda s: None)
        with self.assertRaises(FetchError) as cm:
            src.get_url("https://x.io/private/a.md")
        self.assertEqual(cm.exception.reason, "blocked by robots.txt")
        self.assertEqual(src.get_url("https://other.io/private/a.md"), b"# ok")
        self.assertEqual(src.get_url("https://x.io/public/a.md"), b"# ok")
        self.assertEqual(sorted(u for u in seen if u.endswith("/robots.txt")),
                         ["https://other.io/robots.txt", "https://x.io/robots.txt"])

    def test_index_getter(self):
        op = fake_opener([(200, "# Caf\u00e9".encode()), (404, b"")])
        get = index_getter(open_url_source(opener=op, sleep=lambda s: None))
        self.assertEqual(get("https://x.io/llms.txt"), "# Caf\u00e9")
        with self.assertRaises(CLIError) as cm:
            get("https://x.io/gone.txt")
        self.assertEqual(cm.exception.code, 4)
        self.assertIn("cannot fetch https://x.io/gone.txt: HTTP 404", str(cm.exception))

    def test_cache_put_get_manifest(self):
        self.cache.put("docs/a", "https://x.io/docs/a.md", "# A", "md", now=0)
        self.assertEqual(self.cache.get("docs/a"), ("# A", "md"))
        m = self.cache.manifest()["docs/a"]
        self.assertEqual((m["url"], m["type"], m["fetched"]),
                         ("https://x.io/docs/a.md", "md", "1970-01-01T00:00:00Z"))
        self.assertEqual(m["sha256"], hashlib.sha256(b"# A").hexdigest())
        self.assertTrue(os.path.isfile(os.path.join(self.cache.root, "docs", "a.md")))

    def test_cache_type_change_removes_old_file(self):
        self.cache.put("a", "https://x.io/a", "<html>", "html", now=0)
        self.cache.put("a", "https://x.io/a.md", "# A", "md", now=1)
        self.assertFalse(os.path.exists(os.path.join(self.cache.root, "a.html")))
        self.assertEqual(self.cache.get("a"), ("# A", "md"))

    def test_cache_refuses_escape(self):
        with self.assertRaises(ValueError):
            self.cache.put("../evil", "https://x.io/e.md", "x", "md", now=0)

    def test_fetch_llms_uses_cache_and_refetch(self):
        self.cache.put("a", "https://x.io/a.md", "# old", "md", now=0)
        op = fake_opener([(200, b"# B")])
        raw, errors, fetched = fetch_llms(open_url_source(opener=op, sleep=lambda s: None),
                                          [("a", "https://x.io/a.md"), ("b", "https://x.io/b.md")],
                                          self.cache, refetch=False, now=60)
        self.assertEqual(raw, {"a": ("# old", "md"), "b": ("# B", "md")})
        self.assertEqual([u for u in op.urls if not u.endswith("robots.txt")],
                         ["https://x.io/b.md"])
        self.assertEqual((errors, list(fetched)), ({}, ["b"]))
        op2 = fake_opener([(200, b"# new")])
        raw, _, _ = fetch_llms(open_url_source(opener=op2, sleep=lambda s: None),
                               [("a", "https://x.io/a.md")], self.cache, refetch=True, now=120)
        self.assertEqual(raw["a"], ("# new", "md"))

    def test_fetch_llms_failure_keeps_cached_copy(self):
        self.cache.put("a", "https://x.io/a.md", "# old", "md", now=0)
        op = fake_opener([(404, b"")])
        raw, errors, _ = fetch_llms(open_url_source(opener=op, sleep=lambda s: None),
                                    [("a", "https://x.io/a.md")], self.cache, refetch=True, now=1)
        self.assertEqual((raw["a"], errors["a"]), (("# old", "md"), "HTTP 404"))

    def test_fetch_llms_failure_without_cache(self):
        op = fake_opener([(404, b"")])
        raw, errors, fetched = fetch_llms(open_url_source(opener=op, sleep=lambda s: None),
                                          [("a", "https://x.io/a.md")], self.cache,
                                          refetch=False, now=1)
        self.assertEqual((raw, errors, fetched), ({}, {"a": "HTTP 404"}, {}))


class MarkdownTests(unittest.TestCase):
    @staticmethod
    def norm(html: str) -> str:
        return re.sub(r">\s+<", "><", html)

    def check(self, src: str, expected: str) -> None:
        self.assertEqual(self.norm(md_to_html(src)), self.norm(expected))  # norm also folds the
        # spaces between inline tags that some expected strings keep for readability

    def test_headings_ids_unique(self):
        self.check("# A b\n## A b\nSetext\n===\n### C?",
                   '<h1 id="a-b">A b</h1><h2 id="a-b-1">A b</h2>'
                   '<h1 id="setext">Setext</h1><h3 id="c">C?</h3>')
        self.assertEqual(slugify("Hello, World_x 2"), "hello-world_x-2")

    def test_fenced_code_not_parsed(self):
        self.check("```py\nx = *a* <b>\n```\n~~~\n# no\n~~~",
                   '<pre><code class="language-py">x = *a* &lt;b&gt;</code></pre>'
                   "<pre><code># no</code></pre>")

    def test_unterminated_fence_runs_to_end(self):
        self.check("text\n```\ncode\n# not heading",
                   "<p>text</p><pre><code>code\n# not heading</code></pre>")

    def test_indented_code(self):
        self.check("para\n\n    a < b\n", "<p>para</p><pre><code>a &lt; b</code></pre>")

    def test_inline(self):
        src = ('a `*x*` **b** _c_ [l](u "t") <https://e.x> ![alt](i.png) snake_case_name'
               "  \nnext")
        self.check(src, '<p>a <code>*x*</code> <strong>b</strong> <em>c</em> '
                        '<a href="u" title="t">l</a> <a href="https://e.x">https://e.x</a> '
                        "alt snake_case_name<br>next</p>")

    def test_lists_nested(self):
        self.check("- a\n- b\n  1. c\n  2. d\n- e",
                   "<ul><li>a</li><li>b<ol><li>c</li><li>d</li></ol></li><li>e</li></ul>")

    def test_blockquote_hr(self):
        self.check("> q *x*\n\n---", "<blockquote><p>q <em>x</em></p></blockquote><hr>")

    def test_table(self):
        self.check("| a | b |\n|---|:-:|\n| 1 | x\\|y |",
                   "<table><thead><tr><th>a</th><th>b</th></tr></thead>"
                   "<tbody><tr><td>1</td><td>x|y</td></tr></tbody></table>")

    def test_raw_html_passes_script_dropped(self):
        out = self.norm(md_to_html("<details><summary>S</summary>\n\nbody\n</details>\n"
                                   "<script>x()</script>"))
        self.assertIn("<details><summary>S</summary>", out)
        self.assertIn("<p>body</p>", out)
        self.assertNotIn("x()", out)

    def test_front_matter(self):
        src = '---\ntitle: "T"\ndescription: D d\n---\n# H'
        self.assertEqual(front_matter(src), ({"title": "T", "description": "D d"}, "# H"))
        self.assertEqual(md_to_html(src), '<h1 id="h">H</h1>')

    def test_mdx_imports_comments_dropped(self):
        self.check("import X from './x'\nexport const y = 1\n{/* note */}\ntext", "<p>text</p>")

    def test_mdx_components(self):
        src = ('<CardGroup cols={2}>\n<Card title="Go" href="/go">\nGo docs\n</Card>\n'
               "<Note title='Hi'>\nkeep me\n</Note>\n</CardGroup>")
        self.check(src, '<p><a href="/go">Go</a></p><p>Go docs</p>'
                        "<p><strong>Hi</strong></p><p>keep me</p>")

    def test_mdx_multiline_tag_and_dedent(self):
        src = ('<Tabs>\n  <Tab\n    title="npm"\n  >\n    ```bash\n    npm i x\n    ```\n'
               "  </Tab>\n</Tabs>")
        self.check(src, '<p><strong>npm</strong></p>'
                        '<pre><code class="language-bash">npm i x</code></pre>')

    def test_mdx_inline_component(self):
        self.check("<Note>Read [run](/r).</Note>", '<p>Read <a href="/r">run</a>.</p>')

    def test_mdx_unclosed_component_keeps_text(self):
        self.check("<Note>\nstill here\n\n## After",
                   '<p>still here</p><h2 id="after">After</h2>')

    def test_mdx_generic_in_prose_kept(self):
        self.check("Use Vec<String> here", "<p>Use Vec&lt;String&gt; here</p>")

    def test_mdx_tag_in_indented_code_kept(self):
        self.check('para\n\n    <Card title="x" />\n',
                   '<p>para</p><pre><code>&lt;Card title="x" /&gt;</code></pre>')

    def test_jsx_in_code_kept(self):
        self.check('```jsx\n<Card title="x" />\n```',
                   '<pre><code class="language-jsx">&lt;Card title="x" /&gt;</code></pre>')


SIGNALS_MD = """---
title: T
---
# Install

You can install it. Let's go, your way.

## Step 1: get it

1. Download
2. Run

```bash
tool --flag
def f(x):
```

| a | b |
|---|---|
| 1 | 2 |
"""


class FollowupMarkdownTests(unittest.TestCase):
    check = MarkdownTests.check
    norm = staticmethod(MarkdownTests.norm)

    def test_blockquote_lazy(self):
        self.check("> a\nb\n", "<blockquote><p>a\nb</p></blockquote>")

    def test_mdx_exact_closer(self):
        html = md_to_html("<Tabs>\n<Tab>x</Tab>\n</Tabs>")
        self.assertIn("x", html)
        self.assertNotIn("Tab", html)
        self.assertNotIn("&lt;", html)
        # </Tabs> must not count as the closer of an inline <Tab>
        self.assertIn("&lt;Tab&gt;", md_to_html("see <Tab>x</Tabs> y"))

    def test_list_indented_code(self):
        html = md_to_html("- item\n\n      <Card />\n")
        self.assertIn("<pre><code>&lt;Card /&gt;", html)

    def test_emphasis_hostile_is_fast(self):
        import time
        for src in ("*a" * 20000, "_" * 50000):
            t0 = time.monotonic()
            md_to_html(src)
            self.assertLess(time.monotonic() - t0, 1.0)

    def test_blockquote_lazy_is_fast(self):
        import time
        t0 = time.monotonic()
        html = md_to_html("> a\n" + "b\n" * 25000)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertIn("<blockquote>", html)

    def test_emphasis_still_works(self):
        self.check("*a* **b** _c_ __d__ ~~e~~",
                   "<p><em>a</em> <strong>b</strong> <em>c</em> <strong>d</strong> <del>e</del></p>")

    def test_deep_nesting_capped(self):
        html = md_to_html("> " * 500 + "x")
        self.assertIn("x", html)
        lst = "\n".join("  " * k + "- " + ("x" if k == 499 else "i") for k in range(500))
        self.assertIn("x", md_to_html(lst))
        mdx = "\n".join("<C>" if False else "<Box>" for _ in range(500)) + "\nx\n" \
            + "\n".join("</Box>" for _ in range(500))
        self.assertIn("x", md_to_html(mdx))


class SignalsTests(unittest.TestCase):
    def test_markdown_signals(self):
        self.assertEqual(page_signals(SIGNALS_MD, "md"), {
            "words": 16, "code_ratio": 0.167, "you_per_1k": 187.5, "steps": 3,
            "signature_lines": 1, "headings": 1, "tables": 1})

    def test_html_signals(self):
        html = ("<main><h2>Step one</h2><p>You run it.</p><pre>--verbose\nx = 1</pre>"
                "<ol><li>a</li></ol><table><tr><td>z</td></tr></table></main>")
        s = page_signals(html, "html")
        self.assertEqual((s["headings"], s["tables"], s["steps"], s["signature_lines"]),
                         (1, 1, 2, 1))
        self.assertGreater(s["code_ratio"], 0)

    def test_empty_page(self):
        self.assertEqual(page_signals("", "md")["you_per_1k"], 0.0)


class FinalFixTests(unittest.TestCase):
    """Final whole-branch review fixes."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache}

    def run_main(self, *argv, opener=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env, opener=opener,
                                       sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def test_remove_dot_names_refused(self):
        for d in ("built", "built-src", "built-plans"):
            os.makedirs(os.path.join(self.cache, d))
        for bad in ("..", "."):
            code, _, err = self.run_main("remove", bad)
            self.assertEqual(code, 2, bad)
            self.assertIn("not a docvol name", err)
        for d in ("built", "built-src", "built-plans"):
            self.assertTrue(os.path.isdir(os.path.join(self.cache, d)))
        self.assertTrue(os.path.isdir(self.cache))

    def test_parse_index_skips_bad_ipv6_link(self):
        text = "# T\n- [a](http://[oops/x.md)\n- [b](https://x.io/b.md)\n"
        _, links = parse_index(text, "https://x.io/llms.txt")
        self.assertEqual([l.url for l in links], ["https://x.io/b.md"])

    def test_invalid_urls_not_retried(self):
        calls = []

        def opener(url):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return 404, b""
            raise __import__("http.client").client.InvalidURL("bad")

        sleeps = []
        src = open_url_source(opener=opener, sleep=sleeps.append, delay=0)
        with self.assertRaises(FetchError) as cm:
            src.get_url("https://x.io/a b.md")
        self.assertEqual(cm.exception.reason, "invalid URL")
        self.assertEqual(sleeps, [])
        self.assertEqual(len([c for c in calls if not c.endswith("robots.txt")]), 1)

        def idna(url):
            if url.endswith("/robots.txt"):
                return 404, b""
            raise UnicodeError("label empty")
        src = open_url_source(opener=idna, sleep=sleeps.append, delay=0)
        with self.assertRaises(FetchError):
            src.get_url("https://a..b/x.md")
        self.assertEqual(sleeps, [])

    def test_default_opener_real_bad_urls(self):
        for url in ("https://x.io/a b.md", "https://a..b/x.md"):
            try:
                got = build_fetch.default_opener(url)
            except (ValueError, UnicodeError):
                continue
            self.assertEqual(got[0], 0)

    def test_fetch_llms_records_oserror_and_valueerror(self):
        cache = PageCache(os.path.join(self.tmp, "src"))
        op = fake_opener([(200, b"# A"), (200, b"# B")])
        src = open_url_source(opener=op, sleep=lambda s: None, delay=0)
        with mock.patch.object(PageCache, "put", side_effect=[OSError("disk"), ValueError("key")]):
            raw, errors, _ = fetch_llms(src, [("a", "https://x.io/a.md"),
                                              ("b", "https://x.io/b.md")], cache, True, 0.0)
        self.assertEqual(raw, {})
        self.assertEqual(sorted(errors), ["a", "b"])

    def test_conversion_failure_becomes_stub(self):
        site = {"https://x.io/llms.txt": (200, b"# P\n- [A](https://x.io/a.md)\n"),
                "https://x.io/a.md": (200, b"# A\n\nbody\n")}

        def opener(url):
            if url.endswith("/robots.txt"):
                return 404, b""
            return site.get(url, (404, b""))
        with mock.patch("build_docvol.md_to_html", side_effect=RecursionError), \
                mock.patch("docshelf_build.page_signals", side_effect=RecursionError):
            code, out, err = self.run_main("build", "https://x.io/llms.txt", opener=opener)
        self.assertEqual(code, 0, err)
        plan = load_plan(os.path.join(self.cache, "built-plans", "p.json"))
        self.assertEqual(plan["pages"]["a"]["fetch_error"], "convert failed: RecursionError")
        db = json.load(open(os.path.join(self.cache, "built", "p", "db.json")))
        self.assertIn("convert failed", db["a"])

    def test_conversion_failure_in_writer_only(self):
        site = {"https://x.io/llms.txt": (200, b"# P\n- [A](https://x.io/a.md)\n"),
                "https://x.io/a.md": (200, b"# A\n\nbody\n")}

        def opener(url):
            if url.endswith("/robots.txt"):
                return 404, b""
            return site.get(url, (404, b""))
        with mock.patch("build_docvol.md_to_html", side_effect=RecursionError):
            code, _, err = self.run_main("build", "https://x.io/llms.txt", opener=opener)
        self.assertEqual(code, 0, err)
        db = json.load(open(os.path.join(self.cache, "built", "p", "db.json")))
        self.assertIn("convert failed", db["a"])

    def test_local_txt_stored_absolute_and_missing_message(self):
        a, b = os.path.join(self.tmp, "A"), os.path.join(self.tmp, "B")
        os.makedirs(a)
        os.makedirs(b)
        write(a, "llms.txt", "# L\n- [P](https://x.io/p.md)\n")
        op = lambda url: (404, b"") if url.endswith("robots.txt") else (200, b"# P\n\nhi\n")
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(a)
        self.assertEqual(self.run_main("plan", "llms.txt", "--name", "l", opener=op)[0], 0)
        os.chdir(b)
        code, out, err = self.run_main("build", "l", opener=op)
        self.assertEqual(code, 0, err)
        code, _, err = self.run_main("plan", "nope.txt", opener=op)
        self.assertEqual(code, 2)
        self.assertIn("no such llms.txt file", err)
        code, _, err = self.run_main("build", "nope.txt", opener=op)
        self.assertEqual(code, 2)
        self.assertIn("no such llms.txt file", err)

    def test_read_tree_unreadable_root(self):
        def boom(path):
            raise OSError(2, "No such file or directory")
        with self.assertRaises(CLIError) as cm:
            read_tree("rel/llms.txt", lambda u: "", read_file=boom)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("cannot read", str(cm.exception))

    def test_url_key_dot_host(self):
        self.assertEqual(url_key("http://../x.md", "x.io"), "_/x")
        self.assertEqual(url_key("http://./x.md", "x.io"), "_/x")

    def test_manifest_written_once(self):
        cache = PageCache(os.path.join(self.tmp, "src"))
        op = fake_opener([(200, b"# 1"), (200, b"# 2"), (200, b"# 3")])
        src = open_url_source(opener=op, sleep=lambda s: None, delay=0)
        pages = [("a", "https://x.io/a.md"), ("b", "https://x.io/b.md"),
                 ("c", "https://x.io/c.md")]
        real = build_fetch._atomic_write
        writes = []

        def counting(path, data):
            writes.append(os.path.basename(path))
            real(path, data)
        with mock.patch.object(build_fetch, "_atomic_write", counting):
            fetch_llms(src, pages, cache, True, 0.0)
        self.assertEqual(writes.count("manifest.json"), 1)
        self.assertEqual(sorted(cache.manifest()), ["a", "b", "c"])

    def test_cache_get_sees_unflushed_put(self):
        cache = PageCache(os.path.join(self.tmp, "src"))
        cache.put("a", "https://x.io/a.md", "hello", "md", 0.0)
        self.assertEqual(cache.get("a"), ("hello", "md"))
        cache.flush()
        self.assertEqual(PageCache(cache.root).get("a"), ("hello", "md"))

    def test_looks_html_bom(self):
        self.assertTrue(looks_html("\ufeff<!doctype html>"))


class DetectTests(unittest.TestCase):
    INV = make_inv([("demo.f", "py:function", "1", "api.html#$", "-")])
    LLMS = b"# Demo\n\n## Docs\n\n- [Start](https://d.io/start.md)\n"

    def setUp(self):
        self.site = {}
        self.urls = []

    def opener(self, url):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return 404, b""
        return self.site.get(url, (404, b""))

    def detect(self, src):
        from build_detect import detect
        return detect(src, opener=self.opener, sleep=lambda s: None)

    def test_sphinx_preferred_over_llms(self):
        self.site = {"https://d.io/en/latest/objects.inv": (200, self.INV),
                     "https://d.io/llms.txt": (200, self.LLMS)}
        d = self.detect("https://d.io/en/latest/")
        self.assertEqual((d.kind, d.source), ("sphinx", "https://d.io/en/latest/"))
        self.assertEqual(d.found, [("sphinx", "https://d.io/en/latest/objects.inv"),
                                   ("llms", "https://d.io/llms.txt")])

    def test_llms_only_folder_then_root(self):
        self.site = {"https://d.io/llms.txt": (200, self.LLMS)}
        d = self.detect("https://d.io/docs/index.html")
        self.assertEqual((d.kind, d.source), ("llms", "https://d.io/llms.txt"))
        self.assertIn("https://d.io/docs/llms.txt", self.urls)

    def test_explicit_txt_url_checks_folder_inventory(self):
        self.site = {"https://d.io/llms.txt": (200, self.LLMS),
                     "https://d.io/objects.inv": (200, self.INV)}
        d = self.detect("https://d.io/llms.txt")
        self.assertEqual(d.kind, "sphinx")
        self.assertIn(("llms", "https://d.io/llms.txt"), d.found)

    def test_html_and_bad_inventory_rejected(self):
        self.site = {"https://d.io/objects.inv": (200, b"<html>not found</html>"),
                     "https://d.io/llms.txt": (200, b"<!doctype html><html></html>")}
        d = self.detect("https://d.io/")
        self.assertIsNone(d.kind)
        self.assertEqual(d.found, [])

    def test_local_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "objects.inv"), "wb") as f:
                f.write(self.INV)
            d = self.detect(tmp)
            self.assertEqual((d.kind, d.source), ("sphinx", os.path.realpath(tmp)))
            self.assertEqual(self.urls, [])

    def test_local_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "index.txt")
            with open(path, "wb") as f:
                f.write(self.LLMS)
            d = self.detect(path)
            self.assertEqual((d.kind, d.source), ("llms", os.path.realpath(path)))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env={"HOME": "/nonexistent"},
                                       opener=self.opener, sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def test_cli_prints_type_source_and_doc(self):
        self.site = {"https://d.io/llms.txt": (200, self.LLMS)}
        code, out, _ = self.run_main("detect", "https://d.io/")
        self.assertEqual(code, 0)
        self.assertIn("type: llms\n", out)
        self.assertIn("source: https://d.io/llms.txt\n", out)
        self.assertIn("read: BUILD-llmstxt.md\n", out)

    def test_cli_nothing_found_exit_3(self):
        code, out, err = self.run_main("detect", "https://d.io/")
        self.assertEqual(code, 3)
        self.assertIn("no objects.inv or llms.txt", err)
        self.assertIn("HTTP 404", err)

    def test_cli_network_failure_exit_4(self):
        self.site = {}
        orig = self.opener
        self.opener = lambda url: (0, b"") if not url.endswith("/robots.txt") else orig(url)
        code, _, err = self.run_main("detect", "https://d.io/")
        self.assertEqual(code, 4)
        self.assertIn("network error", err)


CL_INDEX = ("# Site\n## Docs\n- [Ref](https://x.io/ref.md)\n- [Guide](https://x.io/guide.md)\n"
            "- [Thin](https://x.io/thin.md)\n")
CL_REF = ("# Ref\n\n" + "The option sets the value used by the command. " * 40
          + "\n\n```\n" + "".join("--flag%d VALUE\n" % i for i in range(12)) + "```\n"
          + "\n| a | b |\n|---|---|\n| 1 | 2 |\n\n| c | d |\n|---|---|\n| 3 | 4 |\n")
CL_GUIDE = "# Guide\n\n" + "First you open it, then you check that you can see what you need. " * 30 + "\n"
CL_THIN = "# Thin\n\nShort page.\n"


class ClassifyCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache}
        self.site = {
            "https://x.io/llms.txt": (200, CL_INDEX.encode()),
            "https://x.io/ref.md": (200, CL_REF.encode()),
            "https://x.io/guide.md": (200, CL_GUIDE.encode()),
            "https://x.io/thin.md": (200, CL_THIN.encode()),
        }
        self.pages_allowed = True
        self.urls = []
        self.plan_path = os.path.join(self.cache, "built-plans", "site.json")
        self.docvol = os.path.join(self.cache, "built", "site")

    def opener(self, url):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return 404, b""
        if not self.pages_allowed and not url.endswith("llms.txt"):
            return 500, b""
        return self.site.get(url, (404, b""))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env, opener=self.opener,
                                       sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def built(self):
        self.assertEqual(self.run_main("build", "https://x.io/llms.txt", "--name", "site")[0], 0)

    def write_choices(self, text):
        path = os.path.join(self.tmp, "choices.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_refuses_sphinx_and_unbuilt(self):
        os.makedirs(os.path.dirname(self.plan_path))
        with open(self.plan_path, "w") as fh:
            json.dump({"kind": "sphinx", "pages": {}}, fh)
        code, _, err = self.run_main("classify", "site")
        self.assertEqual(code, 2)
        self.assertIn("classify works on llms.txt docvols; Sphinx plans use the role rule", err)
        os.remove(self.plan_path)
        self.assertEqual(self.run_main("classify", "nope")[0], 2)
        self.assertEqual(self.run_main("plan", "https://x.io/llms.txt", "--name", "site")[0], 0)
        code, _, err = self.run_main("classify", "site")
        self.assertEqual(code, 2)
        self.assertIn("build site first", err)

    def test_classify_apply_build_offline(self):
        self.built()
        code, out, err = self.run_main("classify", "site")
        self.assertEqual(code, 0, err)
        self.assertIn("reference 1, stub 1, review 1, decided by a person 0, by an agent 0, "
                      "no signals 0", out)
        self.assertEqual(out.count("\n  words="), 1)
        self.assertIn("thin   ", out)
        self.assertIn("then run: classify site --apply FILE --model YOUR_MODEL_ID", out)
        self.assertNotIn("more:", out)
        path = self.write_choices("stub thin Short\n")
        code, out, _ = self.run_main("classify", "site", "--apply", path, "--model", "t")
        self.assertEqual(code, 0)
        self.assertIn("applied 1", out)
        self.assertIn("left for review: 0", out)
        out = self.run_main("classify", "site")[1]
        self.assertIn("nothing left to review; run: build site", out)
        self.pages_allowed = False
        self.urls.clear()
        code, out, err = self.run_main("build", "site")
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.docvol, "db.json"), encoding="utf-8") as fh:
            self.assertIn("Short", json.load(fh)["thin"])
        self.assertEqual([u for u in self.urls if not u.endswith("robots.txt")],
                         ["https://x.io/llms.txt"])

    def test_limit_below_one_is_usage_error(self):
        self.built()
        for bad in ("0", "-3"):
            code, _, err = self.run_main("classify", "site", "--limit", bad)
            self.assertEqual(code, 2)
            self.assertIn("--limit must be 1 or more", err)

    def test_model_must_be_a_real_agent_id(self):
        self.built()
        path = self.write_choices("full thin\n")
        for bad in ("", "rules-2"):
            code, _, err = self.run_main("classify", "site", "--apply", path, "--model", bad)
            self.assertEqual(code, 2)
            self.assertIn("--model", err)
        self.assertEqual(load_plan(self.plan_path)["pages"]["thin"]["why"], "llms: all")

    def test_apply_exit_2_when_nothing_applied(self):
        self.built()
        path = self.write_choices("full no/such/key\n")
        code, out, _ = self.run_main("classify", "site", "--apply", path)
        self.assertEqual(code, 2)
        self.assertIn("line 1:", out)
        self.assertIn("applied 0", out)

    def test_rest_counts_as_applied(self):
        self.built()
        path = self.write_choices("full REST\n")
        code, out, _ = self.run_main("classify", "site", "--apply", path, "--model", "t")
        self.assertEqual(code, 0)
        self.assertIn("REST: 3 pages set to full", out)
        self.assertIn("left for review: 0", out)

    def test_replan_keeps_choices(self):
        self.built()
        self.run_main("classify", "site")
        path = self.write_choices("stub thin Short\n")
        self.run_main("classify", "site", "--apply", path, "--model", "t")
        first = self.run_main("classify", "site")[1].splitlines()[0]
        self.assertEqual(self.run_main("plan", "https://x.io/llms.txt", "--name", "site")[0], 0)
        self.assertEqual(self.run_main("classify", "site")[1].splitlines()[0], first)
        self.assertEqual(load_plan(self.plan_path)["pages"]["thin"]["why"], "model:t")

    def test_apply_stdin_and_bad_file(self):
        self.built()
        with mock.patch("sys.stdin", io.StringIO("full thin\r\n")):
            code, out, _ = self.run_main("classify", "site", "--apply", "-")
        self.assertEqual(code, 0)
        self.assertIn("applied 1", out)
        self.assertEqual(load_plan(self.plan_path)["pages"]["thin"]["why"], "model:agent")
        path = self.write_choices("hello\nkeep x\n")
        code, out, err = self.run_main("classify", "site", "--apply", path)
        self.assertEqual(code, 2)
        self.assertIn("line 1:", out)
        self.assertEqual(load_plan(self.plan_path)["pages"]["thin"]["why"], "model:agent")


class ClassifyRulesTests(unittest.TestCase):
    def test_rules_id(self):
        self.assertEqual(RULES_ID, "model:rules-2")

    def test_clear_reference(self):
        self.assertEqual(rule_choice({"words": 900, "code_ratio": 0.6, "you_per_1k": 1.0,
                                      "steps": 0, "signature_lines": 40, "headings": 12,
                                      "tables": 3}), "full")

    def test_clear_guide(self):
        self.assertEqual(rule_choice({"words": 1500, "code_ratio": 0.05, "you_per_1k": 25.0,
                                      "steps": 8, "signature_lines": 0, "headings": 6,
                                      "tables": 0}), "stub")

    def test_thin_page_reviewed(self):
        self.assertEqual(rule_choice({"words": 40, "code_ratio": 0.0, "you_per_1k": 0.0,
                                      "steps": 0, "signature_lines": 0, "headings": 0,
                                      "tables": 0}), "review")

    def test_missing_signal_keys_reviewed(self):  # RF 1
        self.assertEqual(rule_choice({}), "review")

    def _fixture_pages(self, split, site):
        with open(os.path.join(HERE, "fixtures", "docshelf_build_classify.json")) as f:
            data = json.load(f)
        return [p for p in data["pages"] if p["site"] == site and p.get("split") == split]

    def _decided(self, pages):
        out = [(rule_choice(p["signals"]), p["label"]) for p in pages]
        return [(c, lab) for c, lab in out if c != "review"]

    def _agreement(self, pages):
        decided = self._decided(pages)
        agree = sum((c == "full") == (lab == "reference") for c, lab in decided)
        return decided, agree

    def _stubbed_reference(self, pages):
        return sum(1 for p in pages
                   if p["label"] == "reference" and rule_choice(p["signals"]) == "stub")

    def test_tuning_bar_calibration_plus_holdout(self):
        # rules-2 was tuned on these two splits together: the bar per site.
        stubbed = 0
        for site in ("langchain", "opencode"):
            pages = (self._fixture_pages("calibration", site)
                     + self._fixture_pages("holdout", site))
            decided, agree = self._agreement(pages)
            self.assertGreater(len(decided), 0, site)
            self.assertGreaterEqual(agree / len(decided), 0.95, site)
            stubbed += self._stubbed_reference(pages)
        self.assertLessEqual(stubbed, 1)

    def test_fresh_split_frozen_figures(self):
        # The fresh split (another site) never took part in tuning. These
        # floors are a regression guard at the figures measured once after
        # the thresholds were frozen (14 of 62 decided, 13 agree, 1 reference
        # page stubbed), not a target.
        pages = self._fixture_pages("fresh", "langchain-ts")
        self.assertEqual(len(pages), 62)
        decided, agree = self._agreement(pages)
        self.assertGreaterEqual(len(decided), 14)
        self.assertGreaterEqual(agree / len(decided), 13 / 14 - 0.001)
        self.assertLessEqual(self._stubbed_reference(pages), 1)


class ClassifyPlanTests(unittest.TestCase):
    REF = {"words": 900, "code_ratio": 0.6, "you_per_1k": 1.0, "steps": 0,
           "signature_lines": 40, "headings": 12, "tables": 3}
    GUIDE = {"words": 1500, "code_ratio": 0.05, "you_per_1k": 25.0, "steps": 8,
             "signature_lines": 0, "headings": 6, "tables": 0}
    THIN = {"words": 40, "code_ratio": 0.0, "you_per_1k": 0.0, "steps": 0,
            "signature_lines": 0, "headings": 0, "tables": 0}

    def pg(self, why="llms: all", keep="full", signals=None, **extra):
        page = {"keep": keep, "title": "T", "section": None, "description": None,
                "why": why, "uri": "u", "signals": dict(self.REF if signals is None else signals)}
        page.update(extra)
        return page

    def test_may_decide(self):
        self.assertTrue(may_decide(self.pg()))
        self.assertTrue(may_decide(self.pg(why="model:rules-1")))
        self.assertFalse(may_decide(self.pg(why="manual")))
        self.assertFalse(may_decide(self.pg(why="override: a/*")))
        self.assertFalse(may_decide(self.pg(why="model:agent")))
        page = self.pg()
        del page["signals"]
        self.assertFalse(may_decide(page))

    def test_run_rules_idempotent(self):  # RF 4
        plan = {"kind": "llms", "pages": {"a": self.pg(keep="stub"),
                                          "b": self.pg(signals=self.GUIDE),
                                          "c": self.pg(signals=self.THIN, why="model:rules-1",
                                                       keep="stub")}}
        run_rules(plan)
        self.assertEqual([plan["pages"][k]["keep"] for k in "abc"], ["full", "stub", "full"])
        self.assertEqual([plan["pages"][k]["why"] for k in "abc"],
                         ["model:rules-2", "model:rules-2", "llms: all"])
        before = json.loads(json.dumps(plan))
        run_rules(plan)
        self.assertEqual(plan, before)

    def test_rules1_pages_redecided(self):  # RF 4
        plan = {"kind": "llms", "pages": {
            "a": self.pg(why="model:rules-1", keep="stub"),
            "b": self.pg(why="model:rules-1", keep="full", signals=self.GUIDE),
            "c": self.pg(why="model:agent", keep="stub"),
            "d": self.pg(why="manual", keep="stub")}}
        run_rules(plan)
        self.assertEqual([plan["pages"][k]["keep"] for k in "abcd"],
                         ["full", "stub", "stub", "stub"])
        self.assertEqual([plan["pages"][k]["why"] for k in "abcd"],
                         ["model:rules-2", "model:rules-2", "model:agent", "manual"])

    def test_run_rules_leaves_people_and_agents(self):
        plan = {"kind": "llms", "pages": {
            "a": self.pg(why="manual", keep="stub"),
            "b": self.pg(why="model:agent", keep="full", signals=self.GUIDE)}}
        before = json.loads(json.dumps(plan))
        run_rules(plan)
        self.assertEqual(plan, before)

    def test_counts_add_up(self):  # RF 1
        nosig = self.pg()
        del nosig["signals"]
        plan = {"kind": "llms", "pages": {
            "a": self.pg(why="model:rules-1", keep="full"),
            "b": self.pg(why="model:rules-1", keep="stub", signals=self.GUIDE),
            "c": self.pg(why="manual", keep="stub"),
            "d": self.pg(why="model:agent"),
            "e": self.pg(signals=self.THIN),
            "f": nosig}}
        c = counts(plan)
        self.assertEqual(c, {"reference": 1, "stub": 1, "person": 1, "agent": 1,
                             "review": 1, "no signals": 1})
        self.assertEqual(sum(c.values()), 6)
        self.assertEqual(bucket(self.pg(why="override: x")), "person")

    def test_preview_markdown(self):
        text = "---\ntitle: X\n---\n# X\n\nUse <Tabs>the thing</Tabs> here.\n"
        self.assertEqual(preview(text, "md"), "Use the thing here.")

    def test_preview_html_and_empty(self):  # RF 3
        html = "<html><body><main><h1>T</h1><p>Body text</p></main></body></html>"
        self.assertEqual(preview(html, "html"), "Body text")
        self.assertEqual(preview("", "md"), "")
        self.assertEqual(preview("---\ntitle: X\n---\n", "md"), "")
        self.assertEqual(preview("x" * 500, "md", 10), "x" * 10)

    def test_review_lines_format_and_paging(self):
        sig = dict(self.THIN, words=300, code_ratio=0.33, you_per_1k=5.0, signature_lines=2,
                   steps=1, tables=0)
        plan = {"kind": "llms", "pages": {
            "k1": self.pg(signals=sig, title="One", section="Sec"),
            "skip": self.pg(why="manual"),
            "k2": self.pg(signals=sig, title="Two")}}
        raw = {"k1": ("# One\n\nHello there.", "md")}
        get = raw.get
        self.assertEqual(review_lines(plan, get, 0, 1), [
            "k1   [Sec] One", "  words=300 code=0.33 you=5.0 sig=2 steps=1 tables=0",
            "  > Hello there."])
        self.assertEqual(review_lines(plan, get, 1, 5), [
            "k2   Two", "  words=300 code=0.33 you=5.0 sig=2 steps=1 tables=0"])


class ClassifyApplyTests(unittest.TestCase):
    def test_parse_basic_and_crlf(self):
        ch, err = parse_choices("full a/b\r\nstub c/d  Short note here  \r\n\n# x\n")
        self.assertEqual(ch, [(1, "full", "a/b", None), (2, "stub", "c/d", "Short note here")])
        self.assertEqual(err, [])

    def test_parse_errors(self):
        ch, err = parse_choices("keep a\nfull\nstub\n")
        self.assertEqual(ch, [])
        self.assertEqual(len(err), 3)
        for i, e in enumerate(err, 1):
            self.assertTrue(e.startswith("line %d:" % i))

    def test_key_with_hash(self):
        ch, err = parse_choices("full a#b")
        self.assertEqual(ch, [(1, "full", "a#b", None)])

    def test_apply(self):
        plan = {"kind": "llms", "pages": {
            "a": {"keep": "full", "why": RULES_ID},
            "b": {"keep": "full", "why": "manual"},
            "c": {"keep": "stub", "why": "override: c*"}}}
        ch, _ = parse_choices("stub a Guide\nfull b\nfull c\nfull zz\n")
        n, msgs = apply_choices(plan, ch, "tester")
        self.assertEqual(n, 1)
        self.assertEqual(msgs, ["line 2: b: decided by a person (manual), skipped",
                                "line 3: c: decided by a person (override), skipped",
                                "line 4: zz: unknown page"])
        self.assertEqual(plan["pages"]["a"]["keep"], "stub")
        self.assertEqual(plan["pages"]["a"]["why"], "model:tester")
        self.assertEqual(plan["pages"]["a"]["description"], "Guide")

    def test_apply_overwrites_agent(self):
        plan = {"kind": "llms", "pages": {"a": {"keep": "full", "why": "model:old"}}}
        n, _ = apply_choices(plan, [(1, "stub", "a", None)], "new")
        self.assertEqual(n, 1)
        self.assertEqual(plan["pages"]["a"]["why"], "model:new")

    def rest_plan(self):
        return {"kind": "llms", "pages": {
            "a": {"keep": "full", "why": "llms: all", "signals": {}},
            "b": {"keep": "full", "why": "llms: all", "signals": {}},
            "r": {"keep": "full", "why": RULES_ID, "signals": {}},
            "ag": {"keep": "full", "why": "model:old", "signals": {}},
            "pe": {"keep": "full", "why": "manual", "signals": {}},
            "ns": {"keep": "full", "why": "llms: all"}}}

    def test_rest_full_sets_only_review_pages(self):
        plan = self.rest_plan()
        ch, err = parse_choices("full REST\n")
        self.assertEqual(err, [])
        n, msgs = apply_choices(plan, ch, "t")
        self.assertEqual(n, 2)
        self.assertEqual(msgs, ["REST: 2 pages set to full"])
        for k in ("a", "b"):
            self.assertEqual(plan["pages"][k]["why"], "model:t")
        self.assertEqual(plan["pages"]["r"]["why"], RULES_ID)
        self.assertEqual(plan["pages"]["ag"]["why"], "model:old")
        self.assertEqual(plan["pages"]["pe"]["why"], "manual")
        self.assertEqual(plan["pages"]["ns"]["why"], "llms: all")

    def test_rest_stub_is_refused(self):
        for text in ("stub REST\n", "stub REST\nfull a\n"):
            ch, err = parse_choices(text)
            self.assertEqual(err, ["line 1: stub REST is not allowed; "
                                   "stub only pages you have read"])
            self.assertTrue(all(c[2] != "REST" for c in ch))

    def test_rest_full_and_explicit_lines_win_in_either_order(self):
        for text in ("stub a\nfull REST\n", "full REST\nstub a\n"):
            plan = self.rest_plan()
            ch, _ = parse_choices(text)
            n, _ = apply_choices(plan, ch, "t")
            self.assertEqual(n, 2)
            self.assertEqual(plan["pages"]["a"]["keep"], "stub")
            self.assertEqual(plan["pages"]["b"]["keep"], "full")

    def test_rest_with_description_is_an_error(self):
        ch, err = parse_choices("full REST dropped\nfull a\n")
        self.assertEqual(err, ["line 1: REST takes no description"])
        self.assertEqual(ch, [(2, "full", "a", None)])

    def test_real_page_named_rest_still_means_bulk(self):
        plan = self.rest_plan()
        plan["pages"]["REST"] = {"keep": "stub", "why": "llms: all", "signals": {}}
        ch, _ = parse_choices("full REST\n")
        apply_choices(plan, ch, "t")
        self.assertEqual(plan["pages"]["REST"]["keep"], "full")
        self.assertEqual(plan["pages"]["a"]["keep"], "full")

    def test_last_write_wins_and_description_stays(self):
        plan = {"kind": "llms", "pages": {"a/b": {"keep": "full", "why": "llms: all"}}}
        ch, _ = parse_choices("stub a/b First\nfull a/b\n")
        n, _ = apply_choices(plan, ch, "t")
        self.assertEqual(n, 2)
        page = plan["pages"]["a/b"]
        self.assertEqual((page["keep"], page["why"], page["description"]),
                         ("full", "model:t", "First"))


class FollowupIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache}
        self.urls = []

    def run_main(self, site, *argv):
        def opener(url):
            self.urls.append(url)
            if url.endswith("/robots.txt"):
                return 404, b""
            return site.get(url, (404, b""))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env, opener=opener,
                                       sleep=lambda s: None)
        return code, out.getvalue()

    def fetched(self):
        return [u for u in self.urls if not u.endswith("robots.txt")]

    def test_other_host_pages_are_stubs(self):
        site = {"https://x.io/llms.txt": (200, b"# Demo\n- [A](https://x.io/a.md)\n"
                                          b"- [Chat](https://discord.gg/x)\n"),
                "https://x.io/a.md": (200, b"# A\n\nText.\n")}
        self.assertEqual(self.run_main(site, "plan", "https://x.io/llms.txt")[0], 0)
        plan = load_plan(os.path.join(self.cache, "built-plans", "demo.json"))
        self.assertEqual(plan["pages"]["a"]["keep"], "full")
        self.assertEqual(plan["pages"]["discord.gg/x"]["keep"], "stub")
        self.assertEqual(plan["pages"]["discord.gg/x"]["why"], "llms: other host")
        self.urls.clear()
        self.assertEqual(self.run_main(site, "build", "demo")[0], 0)
        self.assertEqual(self.fetched(), ["https://x.io/llms.txt", "https://x.io/a.md"])

    def test_replan_of_old_plan_keeps_keys_when_all_on_index_host(self):
        site = {"https://x.io/llms.txt": (200, b"# Demo\n- [A](https://x.io/docs/a.md)\n"
                                          b"- [B](https://x.io/docs/b.md)\n"),
                "https://x.io/docs/a.md": (200, b"# A\n\nText.\n"),
                "https://x.io/docs/b.md": (200, b"# B\n\nText.\n")}
        self.assertEqual(self.run_main(site, "plan", "https://x.io/llms.txt")[0], 0)
        path = os.path.join(self.cache, "built-plans", "demo.json")
        before = load_plan(path)
        keys = sorted(before["pages"])
        self.assertEqual(len(keys), 2)
        self.assertEqual(self.run_main(site, "plan", "https://x.io/llms.txt",
                                       "--name", "demo")[0], 0)
        after = load_plan(path)
        self.assertEqual(sorted(after["pages"]), keys)
        self.assertTrue(all(p["keep"] == "full" for p in after["pages"].values()))

    def test_well_known_txt_not_followed(self):
        idx = ("# Demo\n- [Humans](https://x.io/humans.txt)\n"
               "- [Robots](https://x.io/Robots.txt)\n"
               "- [Sub](https://x.io/sub/llms-a.txt)\n")
        got = []

        def get_text(url):
            got.append(url)
            return {"https://x.io/llms.txt": idx,
                    "https://x.io/sub/llms-a.txt": "# Sub\n- [P](https://x.io/p.md)\n"}[url]
        tree = read_tree("https://x.io/llms.txt", get_text)
        self.assertEqual(got, ["https://x.io/llms.txt", "https://x.io/sub/llms-a.txt"])
        self.assertEqual([e["url"] for e in tree.indexes],
                         ["https://x.io/llms.txt", "https://x.io/sub/llms-a.txt"])

    def test_md_retry_keeps_query(self):
        op = fake_opener([(200, b"<!doctype html><html>x</html>"), (200, b"# Real")])
        src = open_url_source(opener=op, sleep=lambda s: None)
        self.assertEqual(fetch_llms_page(src, "https://x.io/docs/a?lang=py#top"),
                         ("# Real", "md"))
        self.assertEqual(op.urls[-1], "https://x.io/docs/a.md?lang=py")

    def test_local_root_only_subindexes_main_host(self):
        root = "# R\n- [A](https://x.io/a/llms-a.txt)\n- [B](https://x.io/b/llms-b.txt)\n"
        subs = {"https://x.io/a/llms-a.txt": "# A\n- [P](https://x.io/a/p.md)\n",
                "https://x.io/b/llms-b.txt": "# B\n- [Q](https://x.io/b/q.md)\n"}
        tree = read_tree("rel/llms.txt", subs.__getitem__, read_file=lambda p: root)
        self.assertEqual(tree.main_host, "x.io")
        self.assertEqual([p.key for p in tree.pages], ["a/p", "b/q"])


class FollowupHtmlTests(unittest.TestCase):
    def test_on_attributes_dropped(self):
        html = main_content('<main><p onclick="x" ONLOAD="y" class="c">t</p></main>')
        self.assertIn('<p class="c">t</p>', html)
        self.assertNotIn("onclick", html.lower())

    def test_script_urls_dropped(self):
        html = main_content('<main><a href=" JaVaScRiPt:alert(1)">x</a>'
                            '<a href="data:text/html,hi">y</a>'
                            '<a href="java\tscript:alert(1)">w</a>'
                            '<a href="https://x.io">z</a></main>')
        self.assertNotIn("alert", html)
        self.assertNotIn("data:", html)
        self.assertIn("<a>x</a>", html)
        self.assertIn('<a href="https://x.io">z</a>', html)


class MainHostFixTests(unittest.TestCase):
    def test_main_host_from_root_pages(self):
        root = ("# D\n- [A](https://docs.b.io/a.md)\n- [B](https://docs.b.io/b.md)\n"
                "- [C](https://docs.b.io/c.md)\n- [Chat](https://discord.gg/x)\n")
        tree = read_tree("https://docs.a.io/llms.txt", {"https://docs.a.io/llms.txt": root}.__getitem__)
        self.assertEqual(tree.main_host, "docs.b.io")
        plan = make_llms_plan("https://docs.a.io/llms.txt", tree, [])
        keeps = [p["keep"] for p in plan["pages"].values()]
        self.assertEqual((keeps.count("full"), keeps.count("stub")), (3, 1))
        lines = summarize_llms(plan, None)
        warn = [ln for ln in lines if "other hosts" in ln]
        self.assertEqual(len(warn), 1)
        self.assertIn("1 pages on other hosts are stubs (e.g. discord.gg)", warn[0])
        self.assertIn("--full 'discord.gg/*'", warn[0])

    def test_main_host_falls_back_to_index_host(self):
        subs = {"https://x.io/llms.txt": "# D\n- [S](https://x.io/s/llms.txt)\n",
                "https://x.io/s/llms.txt": "# S\n- [P](https://x.io/s/p.md)\n"}
        tree = read_tree("https://x.io/llms.txt", subs.__getitem__)
        self.assertEqual(tree.main_host, "x.io")

    def test_main_host_sub_index_on_main_host_followed(self):
        root = "# D\n- [A](https://docs.b.io/a.md)\n- [S](https://docs.b.io/s/llms.txt)\n"
        subs = {"https://docs.a.io/llms.txt": root,
                "https://docs.b.io/s/llms.txt": "# S\n- [P](https://docs.b.io/s/p.md)\n"}
        tree = read_tree("https://docs.a.io/llms.txt", subs.__getitem__)
        self.assertEqual([p.key for p in tree.pages], ["a", "s/p"])

    def test_local_root_fallback_with_well_known_txt(self):
        root = ("# R\n- [H](https://x.io/humans.txt)\n- [A](https://x.io/a/llms-a.txt)\n"
                "- [B](https://x.io/b/llms-b.txt)\n")
        subs = {"https://x.io/a/llms-a.txt": "# A\n- [P](https://x.io/a/p.md)\n",
                "https://x.io/b/llms-b.txt": "# B\n- [Q](https://x.io/b/q.md)\n"}
        tree = read_tree("rel/llms.txt", subs.__getitem__, read_file=lambda p: root)
        self.assertEqual(tree.main_host, "x.io")
        self.assertEqual([p.key for p in tree.pages], ["a/p", "b/q"])

    def test_other_host_stub_never_decided_and_error_cleared(self):
        self.assertFalse(may_decide({"keep": "stub", "why": "llms: other host",
                                     "signals": {"words": 800}}))
        old = {"pages": {"discord.gg/x": {"keep": "full", "why": "llms: all",
                                          "fetch_error": "boom", "signals": {"words": 1}}}}
        tree = Tree("D", "x.io", [LlmsPage("discord.gg/x", "https://discord.gg/x", "C", None, None)],
                    [], "h")
        page = make_llms_plan("https://x.io/llms.txt", tree, [], old)["pages"]["discord.gg/x"]
        self.assertEqual((page["keep"], page["why"]), ("stub", "llms: other host"))
        self.assertNotIn("fetch_error", page)

    def test_serialize_drops_encoded_script_schemes(self):
        for href in ("&#106;avascript:alert(1)", "&#x6A;avascript:alert(1)",
                     "java&Tab;script:alert(1)"):
            html = main_content('<main><a href="%s">x</a></main>' % href)
            self.assertNotIn("alert", html, href)
        html = main_content('<main><p src="javascript:alert(1)">x</p></main>')
        self.assertNotIn("alert", html)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        import build_archive
        self.ba = build_archive
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_zip(self, entries, symlink=None):
        import zipfile
        path = os.path.join(self.tmp, "a.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, data in entries:
                z.writestr(name, data)
            if symlink:
                zi = zipfile.ZipInfo(symlink)
                zi.external_attr = (0o120777 << 16)
                z.writestr(zi, "/etc/passwd")
        return path

    def unpack(self, path):
        out = os.path.join(self.tmp, "site")
        return out, self.ba.unpack(path, out)

    def test_find_api_htmlzip(self):
        seen = []

        def get(url):
            seen.append(url)
            return 200, json.dumps({"downloads": {"htmlzip": "https://x.example/z/"}}).encode()
        self.assertEqual(self.ba.find_archive("https://sphinx.readthedocs.io/en/latest/", get),
                         "https://x.example/z/")
        self.assertIn("/projects/sphinx/versions/latest/", seen[0])

    def test_find_api_subproject_slug(self):
        seen = []

        def get(url):
            seen.append(url)
            return 200, b"{}"
        self.assertIsNone(self.ba.find_archive("https://a.readthedocs.io/projects/sub/en/v1/", get))
        self.assertIn("/projects/sub/versions/v1/", seen[0])

    def test_find_api_without_htmlzip_then_probe_404(self):
        def get(url):
            return (200, b'{"downloads": {}}') if "api/v3" in url else (404, b"")
        self.assertIsNone(self.ba.find_archive("https://p.readthedocs.io/en/latest/", get))

    def test_find_api_unreachable_probe_200(self):
        def get(url):
            return (0, b"") if "api/v3" in url else (200, b"PK")
        self.assertEqual(self.ba.find_archive("https://p.readthedocs.io/en/latest/", get),
                         "https://p.readthedocs.io/_/downloads/en/latest/htmlzip/")

    def test_find_probe_uses_head_when_given(self):
        calls = []

        def get(url):
            calls.append(url)
            return 404, b""
        found = self.ba.find_archive("https://docs.example/en/stable/guide/", get,
                                     head=lambda u: (200, {}))
        self.assertEqual(found, "https://docs.example/_/downloads/en/stable/htmlzip/")
        self.assertEqual(calls, [])

    def test_find_api_detail_unknown_project(self):
        def get(url):
            return (404, b'{"detail": "Not found."}') if "api/v3" in url else (404, b"")
        self.assertIsNone(self.ba.find_archive("https://p.readthedocs.io/en/latest/", get))

    def test_unpack_finds_build_one_level_down(self):
        path = self.make_zip([("proj-html/objects.inv", "x"), ("proj-html/index.html", "i"),
                              ("proj-html/_static/a.css", "c")])
        out, build = self.unpack(path)
        self.assertEqual(build, os.path.join(out, "proj-html"))
        self.assertTrue(os.path.isfile(os.path.join(build, "_static", "a.css")))

    def test_unpack_index_html_only(self):
        out, build = self.unpack(self.make_zip([("top/index.html", "i")]))
        self.assertEqual(build, os.path.join(out, "top"))

    def test_unpack_no_build(self):
        path = self.make_zip([("readme.txt", "x")])
        with self.assertRaises(CLIError) as cm:
            self.unpack(path)
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "site")))

    def test_unpack_skips_traversal_absolute_symlink(self):
        path = self.make_zip([("../evil", "x"), ("/etc/abs", "x"), ("a/../../evil2", "x"),
                              ("ok/objects.inv", "x")], symlink="ok/link")
        out, build = self.unpack(path)
        self.assertEqual(build, os.path.join(out, "ok"))
        self.assertEqual(os.listdir(build), ["objects.inv"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))
        self.assertFalse(os.path.exists("/etc/abs"))
        self.assertEqual(os.listdir(out), ["ok"])

    def test_unpack_too_many_files(self):
        path = self.make_zip([("d/f%d.html" % i, "x") for i in range(6)] + [("d/objects.inv", "x")])
        with mock.patch.object(self.ba, "MAX_FILES", 5):
            with self.assertRaises(CLIError) as cm:
                self.unpack(path)
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "site")))
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".unpack")], [])

    def test_unpack_too_big(self):
        path = self.make_zip([("d/objects.inv", "x" * 100)])
        with mock.patch.object(self.ba, "MAX_UNPACKED", 50):
            with self.assertRaises(CLIError) as cm:
                self.unpack(path)
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "site")))

    def test_unpack_tar_gz(self):
        import tarfile
        path = os.path.join(self.tmp, "a.tar.gz")
        src = os.path.join(self.tmp, "srcfile")
        with open(src, "w") as f:
            f.write("x")
        with tarfile.open(path, "w:gz") as t:
            t.add(src, arcname="top/objects.inv")
            t.add(src, arcname="../evil")
            link = tarfile.TarInfo("top/ln")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            t.addfile(link)
        out, build = self.unpack(path)
        self.assertEqual(os.listdir(build), ["objects.inv"])

    def test_head_through_source_honours_robots(self):
        calls, heads = [], []

        def opener(url):
            calls.append(url)
            if url.endswith("robots.txt"):
                return 200, b"User-agent: *\nDisallow: /_/\nDisallow: /blocked/\n"
            return 200, b"PK-data"

        def head(url):
            heads.append(url)
            return 200, {"content-length": "7"}
        src = open_url_source(opener=opener, sleep=lambda s: None, delay=0, head_opener=head)
        self.assertEqual(src.head_url("https://h.example/blocked/"), (0, {}))
        self.assertEqual(heads, [])
        self.assertEqual(src.head_url("https://h.example/ok/")[0], 200)
        # probe at a blocked path: no request to the archive URL
        self.assertIsNone(self.ba.find_archive("https://h.example/en/latest/",
                                               lambda u: (404, b""), head=src.head_url))
        self.assertEqual([h for h in heads if "/_/" in h or "/blocked/" in h], [])
        # change check: blocked head means no head request, archive kept
        dest = os.path.join(self.tmp, "src")
        os.makedirs(dest)
        with open(os.path.join(dest, "archive.zip"), "wb") as f:
            f.write(b"PK-data")
        with open(os.path.join(dest, "archive.json"), "w") as f:
            json.dump({"url": "https://h.example/blocked/", "file": "archive.zip", "size": 7}, f)
        n = len(calls)
        self.assertFalse(self.ba.fetch_archive("https://h.example/blocked/", dest, src, False,
                                               head=src.head_url)[1])
        self.assertEqual([h for h in heads if "/blocked/" in h], [])
        self.assertEqual(len(calls), n)

    def test_unpack_tar_member_cap_counts_dirs(self):
        import tarfile
        path = os.path.join(self.tmp, "d.tar.gz")
        with tarfile.open(path, "w:gz") as t:
            for i in range(6):
                d = tarfile.TarInfo("d%d" % i)
                d.type = tarfile.DIRTYPE
                t.addfile(d)
        with mock.patch.object(self.ba, "MAX_FILES", 5):
            with self.assertRaises(CLIError) as cm:
                self.unpack(path)
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "site")))

    def fetch_setup(self, body=b"PK-data"):
        calls = []

        def opener(url):
            calls.append(url)
            return (404, b"") if url.endswith("robots.txt") else (200, body)
        src = open_url_source(opener=opener, sleep=lambda s: None, delay=0)
        dest = os.path.join(self.tmp, "src")
        return calls, src, dest

    def test_fetch_archive_skips_when_unchanged(self):
        calls, src, dest = self.fetch_setup()
        url = "https://h.example/z/"
        path, got = self.ba.fetch_archive(url, dest, src, False)
        self.assertTrue(got)
        self.assertEqual(open(path, "rb").read(), b"PK-data")
        meta = json.load(open(os.path.join(dest, "archive.json")))
        self.assertEqual(meta["url"], url)
        self.assertEqual(meta["size"], 7)
        self.assertEqual(meta["sha256"], hashlib.sha256(b"PK-data").hexdigest())
        n = len(calls)
        path2, got2 = self.ba.fetch_archive(url, dest, src, False)
        self.assertFalse(got2)
        self.assertEqual(path2, path)
        self.assertEqual(len(calls), n)

    def test_fetch_archive_refetch_and_changed(self):
        calls, src, dest = self.fetch_setup()
        url = "https://h.example/z/"
        self.ba.fetch_archive(url, dest, src, False, head=lambda u: (200, {"content-length": "7"}))
        self.assertFalse(self.ba.fetch_archive(
            url, dest, src, False, head=lambda u: (200, {"content-length": "7"}))[1])
        self.assertTrue(self.ba.fetch_archive(
            url, dest, src, False, head=lambda u: (200, {"content-length": "9"}))[1])
        self.assertTrue(self.ba.fetch_archive(url, dest, src, True)[1])

    def test_fetch_archive_failure_raises(self):
        src = open_url_source(opener=lambda u: (404, b""), sleep=lambda s: None, delay=0)
        with self.assertRaises(FetchError):
            self.ba.fetch_archive("https://h.example/z/", os.path.join(self.tmp, "s"), src, False)


class SingleHtmlArchiveTests(unittest.TestCase):
    """Splitting a Sphinx singlehtml archive (Read the Docs htmlzip) per page."""
    BASE = "https://demo.readthedocs.io/en/latest/"
    ZIP = "https://media.example/demo.zip"
    SINGLE = ("<html><body><div role='main'><h1 id='home'>Home</h1><p>Intro <a href='#sec'>s</a>"
              " <a href='#document-guide/a'>ga</a> <a href='#home'>h</a></p>"
              "<div class='toctree-wrapper'>"
              "<span id='document-cmd/opt'></span><section id='opt-page'><h1>opt</h1>"
              "<p>Opt text <a href='#sec'>sec</a> <a href='#opt-page'>self</a>"
              " <a href='#home'>home</a></p></section>"
              "<span id='document-guide/index'></span><section><h1>Guides</h1><p>G idx</p></section>"
              "<span id='document-guide/a'></span><section><h1 id='sec'>Sec</h1><p>A text"
              " <a href='#opt-page'>o</a> <a href='#document-cmd/opt'>opt doc</a></p></section>"
              "</div></div></body></html>")

    def split(self):
        import build_archive
        return build_archive.split_singlehtml(self.SINGLE, ["index", "cmd/opt", "guide/index", "guide/a", "guide/b"])

    def test_split_assigns_chunks_and_the_index_prefix(self):
        pages = self.split()
        self.assertEqual(sorted(pages), ["cmd/opt", "guide/a", "guide/index", "index"])  # guide/b: no marker
        self.assertIn("Intro", pages["index"])
        self.assertNotIn("Opt text", pages["index"])
        self.assertIn("Opt text", pages["cmd/opt"])
        self.assertNotIn("A text", pages["cmd/opt"])
        self.assertIn("A text", pages["guide/a"])
        for html in pages.values():
            self.assertEqual(main_content(html).count("<div"), html.count("<div") - 1)
            self.assertNotIn('id="document-', html)
            self.assertNotIn("id='document-", html)

    def test_cross_chunk_links_are_rewritten_and_same_chunk_kept(self):
        pages = self.split()
        self.assertIn('href="#home"', pages["index"])
        self.assertIn('href="guide/a.html#sec"', pages["index"])
        self.assertIn('href="guide/a.html"', pages["index"])   # #document-guide/a
        self.assertIn('href="../guide/a.html#sec"', pages["cmd/opt"])
        self.assertIn('href="#opt-page"', pages["cmd/opt"])
        self.assertIn('href="../index.html#home"', pages["cmd/opt"])
        self.assertIn('href="../cmd/opt.html#opt-page"', pages["guide/a"])
        self.assertIn('href="../cmd/opt.html"', pages["guide/a"])   # #document-cmd/opt

    FULL = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>T</title>"
            "<link rel='stylesheet' href='s.css'></head><body><nav>SIDEBAR</nav>"
            "<ul class='wy-breadcrumbs'><li>CRUMBS</li></ul>"
            "<div role='main' class='document'><div class='body'><p id='top'>Intro</p>"
            "<span id='document-a'></span><section><h1 id='x'>A</h1><p>A text"
            " <a href='index.html#top'>t</a> <a href='index.html#document-b'>b</a></p></section>"
            "<span id='document-b'></span><section><p>B text <a href='index.html#x'>x</a>"
            " <a href='./index.html#b-own'>own</a> <a id='b-own'></a></p></section>"
            "</div></div><footer>Built with Sphinx on readthedocs.org</footer>"
            "<div class='rst-versions'>FLYOUT</div></body></html>")

    def test_only_the_main_content_lands_in_chunks(self):
        import build_archive
        pages = build_archive.split_singlehtml(self.FULL, ["index", "a", "b"])
        self.assertEqual(sorted(pages), ["a", "b", "index"])
        for html in pages.values():
            for bad in ("<link", "<meta", "<title", "SIDEBAR", "CRUMBS", "Built with",
                        "readthedocs.org", "FLYOUT"):
                self.assertNotIn(bad, html)
            self.assertNotIn(bad := "<head", html)
        self.assertIn("Intro", pages["index"])
        self.assertIn("B text", pages["b"])

    def test_index_html_fragment_links_count_as_fragment_links(self):
        import build_archive
        pages = build_archive.split_singlehtml(self.FULL, ["index", "a", "b"])
        self.assertIn('href="index.html#top"', pages["a"])
        self.assertIn('href="b.html"', pages["a"])          # index.html#document-b
        self.assertIn('href="a.html#x"', pages["b"])
        self.assertIn('href="#b-own"', pages["b"])          # same chunk: plain fragment
        self.assertNotIn("document-", "".join(pages.values()))

    def test_corrupt_deflate_data_means_no_archive_and_no_site(self):
        import build_archive
        import zipfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        zpath = os.path.join(tmp.name, "bad.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("x/index.html", "<p>hello world</p>" * 500)
        with open(zpath, "rb") as f:
            data = bytearray(f.read())
        for i in range(45, 50):
            data[i] ^= 0xFF
        with open(zpath, "wb") as f:
            f.write(bytes(data))
        out = os.path.join(tmp.name, "site")
        with self.assertRaises(CLIError):
            build_archive.unpack(zpath, out)
        self.assertFalse(os.path.exists(out))
        self.assertEqual([n for n in os.listdir(tmp.name) if n.startswith(".unpack")], [])

    def build_cli_setup(self):
        import zipfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache}
        rows = [(e.name, e.role, "1", e.uri, e.dispname) for e in ENTRIES]
        inv_bytes = make_inv(rows)
        zpath = os.path.join(self.tmp, "demo.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("demo-latest/objects.inv", inv_bytes)
            z.writestr("demo-latest/index.html", self.SINGLE)
        with open(zpath, "rb") as f:
            zbytes = f.read()
        api = json.dumps({"downloads": {"htmlzip": self.ZIP}}).encode()
        self.site = {self.BASE + "objects.inv": (200, inv_bytes),
                     "https://readthedocs.org/api/v3/projects/demo/versions/latest/": (200, api),
                     self.ZIP: (200, zbytes),
                     self.BASE + "guide/b.html": (200, b"<div role='main'><p>LIVE B</p></div>")}
        self.urls = []
        self.docvol = os.path.join(self.cache, "built", "demo")

    def opener(self, url):
        self.urls.append(url)
        return self.site.get(url, (404, b""))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env, opener=self.opener,
                                       sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def test_cli_build_splits_the_archive_and_fetches_the_unmarked_page(self):
        self.build_cli_setup()
        self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.urls.clear()
        code, out, err = self.run_main("build", "demo")
        self.assertEqual(code, 0, err)
        pages = [u for u in self.urls if u.startswith(self.BASE) and u.endswith(".html")]
        self.assertEqual(pages, [self.BASE + "guide/b.html"])
        self.assertIn("4 pages from the archive, 1 over HTTP", out)
        db = load(self.docvol, "db.json")
        self.assertIn("Opt text", db["cmd/opt"])
        self.assertNotIn("A text", db["cmd/opt"])
        self.assertIn("A text", db["guide/a"])
        self.assertIn("LIVE B", db["guide/b"])
        self.assertIn("Intro", db["index"])
        for html in db.values():
            self.assertNotIn("document-", html)


class ArchiveCliTests(unittest.TestCase):
    """plan/build/detect with a Read the Docs style HTML archive (GET-only fake
    opener, so the archive comes from the API, not the HEAD probe)."""
    BASE = "https://demo.readthedocs.io/en/latest/"
    ZIP = "https://media.example/demo.zip"

    def setUp(self):
        import zipfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache}
        rows = [(e.name, e.role, "1", e.uri, e.dispname) for e in ENTRIES]
        inv_bytes = make_inv(rows)
        pages = {"index.html": DOCVOL_HTML["index.html"],
                 "cmd/opt.html": DOCVOL_HTML["cmd/opt.html"]}
        for p in ("guide/index.html", "guide/a.html", "guide/b.html"):
            pages[p] = "<div role='main'><p>Guide text %s</p></div>" % p
        self.pages = pages
        zpath = os.path.join(self.tmp, "demo.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            z.writestr("demo-latest/objects.inv", inv_bytes)
            for rel, html in pages.items():
                if rel != "guide/b.html":
                    z.writestr("demo-latest/" + rel, html)
        with open(zpath, "rb") as f:
            zbytes = f.read()
        api = json.dumps({"downloads": {"htmlzip": self.ZIP}}).encode()
        self.site = {self.BASE + "objects.inv": (200, inv_bytes),
                     "https://readthedocs.org/api/v3/projects/demo/versions/latest/":
                     (200, api), self.ZIP: (200, zbytes)}
        for rel, html in pages.items():
            self.site[self.BASE + rel] = (200, html.replace("<p>", "<p>LIVE ").encode())
        self.urls = []
        self.plan_path = os.path.join(self.cache, "built-plans", "demo.json")
        self.docvol = os.path.join(self.cache, "built", "demo")

    def opener(self, url):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return self.site.get(url, (404, b""))
        return self.site.get(url, (404, b""))

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docshelf_build.main(list(argv), env=self.env, opener=self.opener,
                                       sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def page_urls(self):
        return [u for u in self.urls if u.startswith(self.BASE) and u.endswith(".html")]

    def test_plan_and_detect_print_the_archive(self):
        code, out, err = self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.assertEqual(code, 0, err)
        self.assertIn("archive: " + self.ZIP, out)
        self.assertEqual(load_plan(self.plan_path)["archive"], self.ZIP)
        code, out, _ = self.run_main("detect", self.BASE)
        self.assertEqual(code, 0)
        self.assertIn("archive: " + self.ZIP, out)

    def test_build_fetches_only_the_page_missing_from_the_archive(self):
        self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.urls.clear()
        code, out, err = self.run_main("build", "demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.page_urls(), [self.BASE + "guide/b.html"])
        self.assertIn("4 pages from the archive, 1 over HTTP", out)
        db = load(self.docvol, "db.json")
        self.assertIn("Guide text guide/a.html", db["guide/a"])
        self.assertIn("LIVE", db["guide/b"])
        self.assertNotIn("LIVE", db["guide/a"])

    def test_rebuild_does_not_download_the_archive_again(self):
        self.run_main("build", self.BASE, "--name", "demo", "--all")
        self.urls.clear()
        self.assertEqual(self.run_main("build", "demo")[0], 0)
        self.assertNotIn(self.ZIP, self.urls)
        self.urls.clear()
        self.assertEqual(self.run_main("build", "demo", "--refetch")[0], 0)
        self.assertIn(self.ZIP, self.urls)

    def test_no_archive_fetches_every_page(self):
        self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.urls.clear()
        code, out, err = self.run_main("build", "demo", "--no-archive")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.page_urls()), 5)
        self.assertNotIn(self.ZIP, self.urls)
        self.assertNotIn("from the archive", out)

    def test_no_archive_on_the_site_changes_nothing(self):
        del self.site["https://readthedocs.org/api/v3/projects/demo/versions/latest/"]
        code, out, err = self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.assertEqual(code, 0, err)
        self.assertNotIn("archive", out)
        self.assertNotIn("archive", load_plan(self.plan_path))
        self.assertEqual(self.run_main("detect", self.BASE)[1].count("archive"), 0)
        code, out, _ = self.run_main("build", "demo")
        self.assertEqual(len(self.page_urls()), 5)

    def build_with(self, *argv, head=None):
        """run_main with a HEAD-capable opener (open_source gets head_opener)."""
        import build_fetch
        real = build_fetch.open_source

        def patched(*a, **k):
            return real(*a, head_opener=head, **k)
        with mock.patch.object(docshelf_build, "open_source", patched):
            return self.run_main(*argv)

    def assert_page_by_page(self, code, out, err):
        self.assertEqual(code, 0, err)
        self.assertIn("archive not used", err)
        self.assertEqual(len(self.page_urls()), 5)
        self.assertNotIn("from the archive", out)
        self.assertFalse(os.path.exists(os.path.join(self.cache, "built-src", "demo",
                                                     "archive", "site")))

    def test_corrupt_archive_falls_back(self):
        self.site[self.ZIP] = (200, b"PK\x03\x04 not really a zip")
        self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.urls.clear()
        self.assert_page_by_page(*self.run_main("build", "demo"))

    def test_over_cap_archive_falls_back(self):
        import build_archive
        self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.urls.clear()
        with mock.patch.object(build_archive, "MAX_FILES", 2):
            self.assert_page_by_page(*self.run_main("build", "demo"))

    def test_failed_archive_download_falls_back(self):
        self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.site[self.ZIP] = (404, b"")
        self.urls.clear()
        self.assert_page_by_page(*self.run_main("build", "demo"))

    def test_rebuild_downloads_again_on_changed_headers_only(self):
        headers = {"content-length": "1", "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"}

        def head(url):
            return (200, dict(headers)) if url == self.ZIP else (0, {})
        self.build_with("build", self.BASE, "--name", "demo", "--all", head=head)
        headers["content-length"] = str(len(self.site[self.ZIP][1]))  # stored size is real
        self.urls.clear()
        self.build_with("build", "demo", head=head)
        self.assertNotIn(self.ZIP, self.urls)
        headers["last-modified"] = "Tue, 02 Jan 2024 00:00:00 GMT"
        self.urls.clear()
        self.build_with("build", "demo", head=head)
        self.assertIn(self.ZIP, self.urls)
        headers["content-length"] = "999999"
        self.urls.clear()
        self.build_with("build", "demo", head=head)
        self.assertIn(self.ZIP, self.urls)

    def test_robots_disallow_means_no_request_to_the_api(self):
        api = "https://readthedocs.org/api/v3/projects/demo/versions/latest/"
        self.site["https://readthedocs.org/robots.txt"] = (200, b"User-agent: *\nDisallow: /\n")
        code, out, err = self.run_main("plan", self.BASE, "--name", "demo", "--all")
        self.assertEqual(code, 0, err)
        self.assertNotIn(api, self.urls)
        self.assertNotIn("archive", out)
        self.run_main("detect", self.BASE)
        self.assertNotIn(api, self.urls)


    def test_remove_deletes_the_archive_folder(self):
        self.run_main("build", self.BASE, "--name", "demo", "--all")
        folder = os.path.join(self.cache, "built-src", "demo", "archive")
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(self.run_main("remove", "demo")[0], 0)
        self.assertFalse(os.path.exists(folder))


class DeferredMinorsTests(unittest.TestCase):
    """0.4.1: the minors deferred from 0.4.0."""

    def test_stray_brackets_scan_in_bounded_time(self):
        import time
        import build_markdown
        t = time.time()
        build_markdown._inline("[[]" * 40000)
        self.assertLess(time.time() - t, 4)  # quadratic before: about 7 s
        self.assertIn('<a href="u">a [b]</a>', build_markdown._inline("[a [b]](u)"))

    def test_bare_line_after_fence_or_table_row_is_not_lazy(self):
        import build_markdown as bm
        for quote in (["> ```", "> x", "> ```"], ["> | a | b |", "> |---|---|", "> | 1 | 2 |"]):
            html = bm._blocks(quote + ["bare"], {}, False, 0)
            self.assertIn("</blockquote>\n<p>bare</p>", html)
        html = bm._blocks(["> para", "bare"], {}, False, 0)
        self.assertIn("<p>para\nbare</p>", html.replace("parabare", "para\nbare"))

    def _src(self, routes, robots):
        """routes: url -> (status, bytes); robots: origin -> robots text."""
        seen = []

        def opener(url):
            seen.append(url)
            if url.endswith("/robots.txt"):
                text = robots.get(url[:-len("/robots.txt")])
                return (200, text.encode()) if text is not None else (404, b"")
            return routes[url]
        return open_source("https://x.io/docs/", opener=opener, sleep=lambda s: None, delay=0), seen

    def test_redirect_target_is_checked_against_its_own_robots(self):
        src, seen = self._src({"https://x.io/a.html": (301, b"https://y.io/p.html"),
                               "https://y.io/p.html": (200, b"body")},
                              {"https://y.io": "User-agent: *\nDisallow: /\n"})
        self.assertEqual(src.get_quiet("https://x.io/a.html"), (0, b""))
        self.assertNotIn("https://y.io/p.html", seen)
        with self.assertRaises(FetchError):
            src.get_url("https://x.io/a.html")

    def test_allowed_redirect_is_followed_and_loops_end(self):
        src, _ = self._src({"https://x.io/a.html": (302, b"/b.html"),
                            "https://x.io/b.html": (200, b"ok"),
                            "https://x.io/l1": (302, b"/l2"), "https://x.io/l2": (302, b"/l1")}, {})
        self.assertEqual(src.get_url("https://x.io/a.html"), b"ok")
        with self.assertRaises(FetchError) as c:
            src.get_url("https://x.io/l1")
        self.assertIn("too many redirects", str(c.exception))

    def test_default_opener_hands_back_the_redirect(self):
        import urllib.error
        import email.message

        def fake_open(req, timeout=None):
            h = email.message.Message()
            h["Location"] = "https://y.io/z"
            raise urllib.error.HTTPError(req.full_url, 301, "moved", h, None)
        with mock.patch.object(build_fetch._URL_OPENER, "open", fake_open):
            self.assertEqual(build_fetch.default_opener("https://x.io/a"), (301, b"https://y.io/z"))
            self.assertEqual(build_fetch.default_head("https://x.io/a"), (301, {"location": "https://y.io/z"}))

    def test_probe_falls_back_to_get_when_head_is_refused(self):
        import build_archive
        probe = "https://p.readthedocs.io/_/downloads/en/latest/htmlzip/"
        get = lambda url: (0, b"") if "api/v3" in url else (200, b"PK")  # noqa: E731
        for refused in (405, 403, 501, 0):
            self.assertEqual(build_archive.find_archive("https://p.readthedocs.io/en/latest/", get,
                                                        lambda u, r=refused: (r, {})), probe)
        self.assertIsNone(build_archive.find_archive("https://p.readthedocs.io/en/latest/", get,
                                                     lambda u: (404, {})))

    def test_percent_encoded_fragments_resolve(self):
        import build_archive
        html = ("<div role='main'><span id='document-guide/a'></span><p>A <a href='#document-cmd%2Fopt'>o</a>"
                " <a href='#sec%2D1'>s</a></p><span id='document-cmd/opt'></span><section>"
                "<h1 id='sec-1'>S</h1></section></div>")
        pages = build_archive.split_singlehtml(html, ["index", "guide/a", "cmd/opt"])
        self.assertIn('href="../cmd/opt.html"', pages["guide/a"])
        self.assertIn('href="../cmd/opt.html#sec%2D1"', pages["guide/a"])

    def test_single_page_check_ignores_extra_html_files(self):
        import docshelf_build as db
        marker = "<div role='main'><p>Intro</p><span id='document-a'></span><p>A</p></div>"
        uris = ["index.html", "a.html", "b.html"]
        # every page present: a normal archive, left alone
        html = {"index.html": marker, "a.html": "<p>a</p>", "b.html": "<p>b</p>"}
        db._split_single_page(None, uris, html, {})
        self.assertEqual(html["a.html"], "<p>a</p>")
        # all pages but index.html missing: split
        html = {"index.html": marker}
        errors = {"a.html": "missing", "b.html": "missing"}
        db._split_single_page(None, uris, html, errors)
        self.assertIn("A", html["a.html"])
        self.assertEqual(list(errors), ["b.html"])


class DoxygenJsTests(unittest.TestCase):
    def test_search_data(self):
        text = "var searchData=\n[\n  ['_5fget_0',['_get',['../a.html#x',1,'ns::A::_get()']]]\n];\n"
        self.assertEqual(js_value(text, "searchData"),
                         [["_5fget_0", ["_get", ["../a.html#x", 1, "ns::A::_get()"]]]])

    def test_menudata_bare_keys_and_comment(self):
        text = '/* @licstart x */ var menudata={children:[{text:"Main Page",url:"index.html"}]}'
        self.assertEqual(js_value(text, "menudata"),
                         {"children": [{"text": "Main Page", "url": "index.html"}]})

    def test_escapes(self):
        self.assertEqual(js_value(r"var v=['it\'s','a\\b','\u00e9'];", "v"), ["it's", "a\\b", "\u00e9"])

    def test_object_with_int_keys(self):
        self.assertEqual(js_value('var s =\n{\n  0: "all",\n  1: "classes"\n};', "s"),
                         {"0": "all", "1": "classes"})

    def test_html_instead_of_js(self):
        with self.assertRaisesRegex(DoxygenFormatError, "blocking automated requests"):
            js_value("<!DOCTYPE html><title>Just a moment...</title>", "searchData")

    def test_missing_var_and_garbage(self):
        for text in ("var other=[1];", "var searchData=[1,", "var searchData=[foo()]"):
            with self.assertRaises(DoxygenFormatError):
                js_value(text, "searchData")


class DoxygenSourceTests(unittest.TestCase):
    BASE = "https://docs.example.org/docs/"

    def src(self, responses, robots=None):
        return build_fetch.open_source(self.BASE, opener=fake_opener(responses, robots),
                                       sleep=lambda s: None)

    def test_url_200_and_404(self):
        self.assertEqual(self.src([(200, b"x")]).file("search/searchdata.js"), b"x")
        self.assertIsNone(self.src([(404, b"")]).file("search/searchdata.js"))

    def test_url_other_status_is_network_error(self):
        with self.assertRaises(CLIError) as cm:
            self.src([(503, b"")] * 4).file("menudata.js")
        self.assertEqual(cm.exception.code, 4)
        self.assertIn("menudata.js", str(cm.exception))

    def test_url_blocked_by_robots(self):
        with self.assertRaises(FetchError):
            self.src([], robots="User-agent: *\nDisallow: /docs/search/").file("search/x.js")

    def test_local(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "search/searchdata.js", "v")
            s = build_fetch.open_source(root)
            self.assertEqual(s.file("search/searchdata.js"), b"v")
            self.assertIsNone(s.file("nope.js"))
            self.assertIsNone(s.file("../outside"))


DOXY_SEARCHDATA = """var indexSectionsWithContent =
{
  0: "abg",
  1: "gm",
  2: "g",
  3: "abcdefghijk",
  4: "g",
  5: "i",
  6: "g"
};
var indexSectionNames =
{
  0: "all",
  1: "classes",
  2: "files",
  3: "functions",
  4: "defines",
  5: "groups",
  6: "pages"
};
var indexSectionLabels =
{
  0: "All",
  1: "Data Structures",
  2: "Files",
  3: "Functions",
  4: "Macros",
  5: "Modules",
  6: "Pages"
};
"""


def doxy_search_site():
    """A hand-made Doxygen search index: rel path -> bytes."""
    sd = lambda rows: ("var searchData=\n[\n  " + ",\n  ".join(rows) + "\n];\n").encode()
    return {
        "search/searchdata.js": DOXY_SEARCHDATA.encode(),
        "search/classes_0.js": sd(["['glfwimage_0',['GLFWimage',['../structGLFWimage.html',1,'']]]"]),
        "search/classes_1.js": sd(["['mat_0',['Mat',['../classcv_1_1Mat.html',1,'cv']]]"]),
        "search/files_0.js": sd(["['glfw3_2eh_0',['glfw3.h',['../glfw3_8h.html',1,'']]]"]),
        "search/functions_0.js": sd([
            "['_5fget_0',['_get',['../a.html#x',1,'ns::A::_get()'],"
            "['../a.html#y',1,'ns::A::_get(const std::vector&lt; int &gt; &amp;v)']]]"]),
        "search/functions_a.js": sd([
            "['glfwkey_0',['glfwKey',['../group__input.html#ga1',1,'glfw3.h'],"
            "['../group__input.html#ga1',1,'glfw3.h']]]"]),
        "search/defines_0.js": sd([
            "['glfw_5fkey_5fescape_0',['GLFW_KEY_ESCAPE',['../group__keys.html#gaac',1,'glfw3.h']]]"]),
        "search/groups_0.js": sd(["['input_0',['Input reference',['../group__input.html',1,'']]]"]),
        "search/pages_0.js": sd(["['getting_0',['Getting started',['../quick_guide.html',1,'']]]"]),
        "search/all_0.js": sd(["['x_0',['x',['../x.html',1,'']]]"]),
    }


class DoxygenSearchIndexTests(unittest.TestCase):
    def read(self, files):
        asked = []

        def get(rel):
            asked.append(rel)
            return files.get(rel)
        return read_search_index(get), asked

    def entry(self, idx, name):
        found = [e for e in idx.entries if e.name == name]
        self.assertTrue(found, name)
        return found

    def test_hex_file_names_and_bare_c_names(self):
        idx, asked = self.read(doxy_search_site())
        self.assertEqual(self.entry(idx, "glfwKey"),
                         [InvEntry("glfwKey", "doxygen:Function", 1, "group__input.html#ga1", "-")])
        self.assertIn("search/functions_a.js", asked)
        self.assertNotIn("search/functions_10.js", asked)
        self.assertFalse([r for r in asked if r.startswith("search/all_")])
        self.assertEqual(idx.kind, "search")

    def test_overloads_and_entities(self):
        idx, _ = self.read(doxy_search_site())
        got = self.entry(idx, "ns::A::_get")
        self.assertEqual([(e.uri, e.dispname, e.role) for e in got],
                         [("a.html#x", "ns::A::_get()", "doxygen:Function"),
                          ("a.html#y", "ns::A::_get(const std::vector< int > &v)", "doxygen:Function")])

    def test_types(self):
        idx, _ = self.read(doxy_search_site())
        self.assertEqual(self.entry(idx, "cv::Mat")[0].role, "doxygen:Class")
        self.assertEqual(self.entry(idx, "GLFWimage")[0].role, "doxygen:Struct")
        self.assertEqual(self.entry(idx, "GLFW_KEY_ESCAPE")[0].role, "doxygen:Macro")
        self.assertEqual(self.entry(idx, "glfw3.h")[0].role, "doxygen:File")
        self.assertEqual(self.entry(idx, "Input reference")[0].role, "doxygen:Module")
        self.assertEqual(self.entry(idx, "Getting started")[0].role, "std:doc")

    def test_missing_files_warn(self):
        idx, _ = self.read(doxy_search_site())
        missing = [w for w in idx.warnings if "functions_" in w]
        self.assertEqual(len(missing), 9)
        self.assertIn("search/searchdata.js", [rel for rel, _ in idx.files])

    def test_blocked_file_warns(self):
        files = doxy_search_site()
        files["search/functions_0.js"] = b"<html>blocked</html>"
        idx, _ = self.read(files)
        self.assertTrue([w for w in idx.warnings if "blocking automated requests" in w])
        self.entry(idx, "glfwKey")

    def test_no_searchdata(self):
        with self.assertRaises(DoxygenFormatError):
            self.read({})

    def test_page_uri(self):
        self.assertEqual(page_uri("../group__window.html#ga5c", "search/"), "group__window.html#ga5c")
        self.assertEqual(page_uri("classwx_window.html#a9", ""), "classwx_window.html#a9")

    def test_member_name(self):
        ns = {"glfw3.h", "Input reference"}
        self.assertEqual(member_name("glfwKey", "glfw3.h", "doxygen:Function", ns), ("glfwKey", "-"))
        self.assertEqual(member_name("f", "Input reference", "doxygen:Function", ns), ("f", "-"))
        self.assertEqual(member_name("f", "util.hpp", "doxygen:Function", set()), ("f", "-"))
        self.assertEqual(member_name("SetSize", "wxWindow", "doxygen:Function", ns),
                         ("wxWindow::SetSize", "-"))
        self.assertEqual(member_name("_A", "cv::_A::_A(int (*f)(int)) const", "doxygen:Function", ns),
                         ("cv::_A::_A", "cv::_A::_A(int (*f)(int)) const"))
        self.assertEqual(member_name("x", "", "doxygen:Variable", ns), ("x", "-"))


def doxy_page(contents, nav=""):
    return ('<html><body><div id="top"><a href="nav_target.html">Navigation</a>%s</div>'
            '<div class="contents">%s</div></body></html>' % (nav, contents))


DOXY_MENU = {"children": [
    {"text": "Main Page", "url": "index.html"},
    {"text": "Related Pages", "url": "pages.html"},
    {"text": "Categories", "url": "modules.html"},
    {"text": "Classes", "url": "annotated.html", "children": [
        {"text": "Class List", "url": "annotated.html"},
        {"text": "Class Index", "url": "classes.html"},
        {"text": "Class Members", "url": "functions.html", "children": [
            {"text": "All", "url": "functions.html", "children": [
                {"text": "a", "url": "functions_a.html#index_a"}]},
            {"text": "Functions", "url": "functions_func.html", "children": [
                {"text": "s", "url": "functions_func_s.html#index_s"}]}]}]},
    {"text": "Files", "url": "files.html", "children": [
        {"text": "File Members", "url": "globals.html", "children": [
            {"text": "Macros", "url": "globals_defs.html", "children": [
                {"text": "e", "url": "globals_defs_e.html#index_e"},
                {"text": "e", "url": "globals_defs_e.html#index_e"},
                {"text": "w", "url": "globals_defs_w.html#index_w"}]}]}]}]}

DOXY_ANNOTATED = doxy_page(
    '<div class="textblock">Here are the classes:</div><table class="directory">'
    '<tr><td class="entry"><a class="el" href="classwx_window.html">wxWindow</a></td>'
    '<td class="desc">Base, see <a class="el" href="overview_windows.html">Window overview</a></td></tr>'
    '<tr><td class="entry"><a class="el" href="structwx_point.html">wxPoint</a></td>'
    '<td class="desc">A point</td></tr></table>')
DOXY_FUNC_S = doxy_page(
    '<h3><a id="index_s"></a>- s -</h3><ul>'
    '<li>SetSize()\n: <a class="el" href="classwx_window.html#a9">wxWindow</a>\n'
    ', <a class="el" href="classwx_frame.html#a3">wxFrame</a>\n</li></ul>')
DOXY_DEFS_W = doxy_page(
    '<h3><a id="index_w"></a>- w -</h3><ul>'
    '<li>wxUSE_X\n: <a class="el" href="defs_8h.html#a1">defs.h</a>\n</li></ul>')


def doxy_menu_site():
    return {
        "menudata.js": ("/* @licstart */ var menudata=" + json.dumps(DOXY_MENU)).encode(),
        "annotated.html": DOXY_ANNOTATED.encode(),
        "files.html": doxy_page('<table class="directory"><tr><td class="entry">'
                                '<a class="el" href="defs_8h.html">defs.h</a></td></tr></table>').encode(),
        "functions_func.html": doxy_page("<ul></ul>").encode(),
        "functions_func_s.html": DOXY_FUNC_S.encode(),
        "globals_defs.html": doxy_page("<ul></ul>").encode(),
        "globals_defs_e.html": doxy_page("<ul></ul>").encode(),
        "globals_defs_w.html": DOXY_DEFS_W.encode(),
    }


class DoxygenMenuIndexTests(unittest.TestCase):
    def read(self, files):
        logged = []
        idx = read_menu_index(files.get, log=logged.append)
        return idx, logged

    def names(self, entries):
        return sorted((e.name, e.role, e.uri) for e in entries)

    def test_menu_pages(self):
        pages = menu_pages(DOXY_MENU)
        self.assertEqual(pages.count(("globals_defs_e.html", "doxygen:Macro")), 1)
        self.assertIn(("functions_func_s.html", "doxygen:Function"), pages)
        self.assertIn(("annotated.html", "doxygen:Class"), pages)
        self.assertIn(("modules.html", "doxygen:Module"), pages)
        self.assertIn(("pages.html", "std:doc"), pages)
        rels = [rel for rel, _ in pages]
        for skipped in ("functions.html", "functions_a.html", "classes.html", "index.html"):
            self.assertNotIn(skipped, rels)

    def test_member_page_owners(self):
        got = parse_member_page(DOXY_FUNC_S, "doxygen:Function", set())
        self.assertEqual(self.names(got), [
            ("wxFrame::SetSize", "doxygen:Function", "classwx_frame.html#a3"),
            ("wxWindow::SetSize", "doxygen:Function", "classwx_window.html#a9")])

    def test_member_page_file_scope_is_bare(self):
        got = parse_member_page(DOXY_DEFS_W, "doxygen:Macro", {"defs.h"})
        self.assertEqual(self.names(got), [("wxUSE_X", "doxygen:Macro", "defs_8h.html#a1")])

    def test_navigation_outside_contents_ignored(self):
        got = parse_member_page(doxy_page("<ul></ul>", '<ul><li>x : <a href="y.html#1">Y</a></li></ul>'),
                                "doxygen:Function", set())
        self.assertEqual(got, [])

    def test_list_page(self):
        got = parse_list_page(DOXY_ANNOTATED, "doxygen:Class")
        self.assertEqual(self.names(got), [
            ("wxPoint", "doxygen:Struct", "structwx_point.html"),
            ("wxWindow", "doxygen:Class", "classwx_window.html")])

    def test_read_with_menudata(self):
        idx, logged = self.read(doxy_menu_site())
        self.assertEqual(idx.kind, "menu")
        names = self.names(idx.entries)
        self.assertIn(("wxWindow::SetSize", "doxygen:Function", "classwx_window.html#a9"), names)
        self.assertIn(("wxUSE_X", "doxygen:Macro", "defs_8h.html#a1"), names)
        self.assertTrue([m for m in logged if re.search(r"reading \d+ Doxygen index pages", m)])
        self.assertTrue([w for w in idx.warnings if "modules.html" in w])

    def test_read_without_menudata(self):
        files = doxy_menu_site()
        del files["menudata.js"]
        files["globals_defs.html"] = doxy_page(
            '<div class="qindex"><a href="globals_defs_w.html#index_w">w</a></div><ul></ul>').encode()
        files["functions_func.html"] = doxy_page(
            '<div class="qindex"><a href="functions_func_s.html#index_s">s</a></div><ul></ul>').encode()
        idx, _ = self.read(files)
        names = self.names(idx.entries)
        self.assertIn(("wxWindow::SetSize", "doxygen:Function", "classwx_window.html#a9"), names)
        self.assertIn(("wxUSE_X", "doxygen:Macro", "defs_8h.html#a1"), names)

    def test_nothing_found(self):
        with self.assertRaises(DoxygenFormatError):
            self.read({})



def dx(name, role, uri, disp="-"):
    return InvEntry(name, role, 1, uri, disp)


class DoxygenPlanTests(unittest.TestCase):
    def test_site_header(self):
        h = site_header('<!-- Generated by Doxygen 1.9.1 --><title>GLFW: Main</title>'
                        '<div id="projectname">GLFW<span id="projectnumber">&#160;3.4.0</span></div>')
        self.assertEqual(h, {"project": "GLFW", "version": "3.4.0", "doxygen": "1.9.1"})
        h = site_header('<title>Documentation | wxWidgets</title>'
                        '<span id="projectnumber">Version: 3.2.13</span>')
        self.assertEqual((h["project"], h["version"]), ("wxWidgets", "3.2.13"))
        self.assertEqual(site_header(""), {"project": "", "version": "", "doxygen": ""})

    def plan(self, entries, overrides=()):
        return make_plan("https://docs.example.org/api/", "sha", {"project": "Demo", "version": "1"},
                         entries, list(overrides), kind="doxygen")

    ENTRIES = [
        dx("Input reference", "doxygen:Module", "group__input.html"),
        dx("glfwKey", "doxygen:Function", "group__input.html#ga1"),
        dx("glfw3.h", "doxygen:File", "glfw3_8h.html"),
        dx("Getting started", "std:doc", "quick_guide.html"),
        dx("main.md", "doxygen:File", "main_8md.html"),
        dx("src", "doxygen:File", "dir_abc.html"),
        dx("cv::Mat", "doxygen:Class", "classcv_1_1Mat.html"),
    ]

    def test_rule(self):
        plan = self.plan(self.ENTRIES)
        pages = plan["pages"]
        self.assertEqual(plan["kind"], "doxygen")
        self.assertEqual(plan["rule"], "doxygen-members")
        self.assertEqual(pages["group__input"]["keep"], "full")
        self.assertEqual(pages["group__input"]["title"], "Input reference")
        self.assertEqual(pages["glfw3_8h"]["keep"], "stub")
        self.assertEqual(pages["quick_guide"]["keep"], "stub")
        self.assertEqual(pages["classcv_1_1Mat"]["keep"], "full")
        self.assertNotIn("main_8md", pages)
        self.assertNotIn("dir_abc", pages)
        self.assertEqual(plan["types"]["Function"], 1)

    def test_override(self):
        plan = self.plan(self.ENTRIES, [("stub", "group__*")])
        self.assertEqual(plan["pages"]["group__input"]["keep"], "stub")

    def test_sphinx_unchanged(self):
        plan = make_plan("https://x/", "s", {}, [InvEntry("f", "py:function", 1, "a.html#f", "-")], [])
        self.assertEqual(plan["kind"], "sphinx")
        self.assertEqual(plan["rule"], "roles")

    def test_summary(self):
        plan = self.plan(self.ENTRIES)
        plan["index"] = "search"
        text = "\n".join(summarize(plan, None))
        self.assertIn("index: search", text)
        self.assertIn("Function 1", text)

    def test_read_doxygen_prefers_search_and_hashes(self):
        files = doxy_search_site()
        files.update(doxy_menu_site())
        files["index.html"] = b'<div id="projectname">Demo</div>'
        sha1, header, entries, idx = read_doxygen(files.get)
        sha2, _, _, _ = read_doxygen(files.get)
        self.assertEqual(idx.kind, "search")
        self.assertEqual(sha1, sha2)
        self.assertEqual(header["project"], "Demo")
        self.assertTrue(entries)

    def test_read_doxygen_falls_back_to_menu(self):
        files = doxy_menu_site()
        files["search/searchdata.js"] = b"var nothing = 1;"
        logged = []
        _, _, _, idx = read_doxygen(files.get, log=logged.append)
        self.assertEqual(idx.kind, "menu")
        self.assertTrue([w for w in idx.warnings if "search index not readable" in w])


DOXY_MEMBER = ('<a id="ga5c"></a><h2 class="memtitle">glfwCreateWindow()</h2>'
               '<div class="memitem"><div class="memproto">GLFWwindow * glfwCreateWindow (int width)</div>'
               '<div class="memdoc">Creates a window.</div></div>')
DOXY_GRAPH = ('<div class="dynheader">Collaboration diagram:</div><div class="dyncontent">'
              '<img src="g.png" usemap="#m" alt=""/><map name="m"><area href="x.html" alt="X"/></map></div>')


def doxy_full_page(wrap=lambda x: x):
    return ('<html><head><script>var x;</script></head><body>'
            '<div id="top"><div id="main-menu">MenuText</div><div id="MSearchBox">SearchBoxText</div></div>'
            '<div id="side-nav"><div id="nav-tree">TreeText</div></div>'
            '<div id="doc-content">' + wrap(
                '<div class="header"><div class="summary"><a href="#func-members">Functions</a></div>'
                '<div class="headertitle"><div class="title">Window reference</div></div></div>'
                '<div class="contents"><p>Brief. <a href="#details">More...</a></p>'
                + DOXY_GRAPH + DOXY_MEMBER + '</div>') +
            '<hr class="footer"/><address class="footer">Generated by doxygen 1.9.1</address>'
            '</div></body></html>')


class DoxygenHtmlTests(unittest.TestCase):
    def check(self, out):
        for want in ("Window reference", 'id="ga5c"', "glfwCreateWindow (int width)", "Creates a window."):
            self.assertIn(want, out)
        for unwanted in ("More...", "<map", "Collaboration diagram", "MenuText", "TreeText",
                         "SearchBoxText", "Generated by", "var x"):
            self.assertNotIn(unwanted, out)

    def test_doxygen_page(self):
        self.check(main_content(doxy_full_page()))

    def test_doxygen_awesome_wrappers(self):
        self.check(main_content(doxy_full_page(lambda x: '<div class="wrap"><div>' + x + '</div></div>')))

    def test_non_doxygen_page_unchanged(self):
        page = '<html><body><nav>N</nav><div role="main"><p>Body</p></div></body></html>'
        self.assertEqual(main_content(page), "<p>Body</p>")


DOXY_CLI_SEARCHDATA = """var indexSectionsWithContent = { 0: "dg", 1: "d", 2: "g" };
var indexSectionNames = { 0: "all", 1: "functions", 2: "pages" };
var indexSectionLabels = { 0: "All", 1: "Functions", 2: "Pages" };
"""


def doxy_fn_js(*names):
    rows = ["['%s_0',['%s',['../group__demo.html#ga%d',1,'demo.h']]]" % (n.lower(), n, i)
            for i, n in enumerate(names)]
    return "var searchData=\n[\n  " + ",\n  ".join(rows) + "\n];\n"


class DoxygenCliTests(unittest.TestCase):
    run_main = CliTests.run_main

    def setUp(self):
        CliTests.setUp(self)
        self.dox = os.path.join(self.tmp, "dox")
        write(self.dox, "index.html", '<div id="projectname">Demo<span id="projectnumber">1.2</span></div>')
        write(self.dox, "search/searchdata.js", DOXY_CLI_SEARCHDATA)
        write(self.dox, "search/functions_0.js", doxy_fn_js("doThing"))
        write(self.dox, "search/pages_0.js",
              "var searchData=[['guide_0',['Guide page',['../guide.html',1,'']]]];")
        write(self.dox, "group__demo.html", doxy_page(
            '<a id="ga0"></a><h2 class="memtitle">doThing()</h2><div class="memdoc">Thing doc</div>'
            '<a id="ga1"></a><h2 class="memtitle">doMore()</h2><div class="memdoc">More doc</div>'))
        write(self.dox, "guide.html", doxy_page("<p>Long prose</p>"))

    def entries(self, name="demo"):
        return load(os.path.join(self.cache, "built", name), "index.json")["entries"]

    def test_detect_search(self):
        code, out, err = self.run_main("detect", self.dox)
        self.assertEqual(code, 0, err)
        for want in ("type: doxygen\n", "index: search\n", "read: BUILD-doxygen.md\n",
                     "source: %s\n" % self.dox):
            self.assertIn(want, out)

    def test_detect_from_page(self):
        code, out, err = self.run_main("detect", os.path.join(self.dox, "group__demo.html"))
        self.assertEqual(code, 0, err)
        self.assertIn("source: %s\n" % self.dox, out)

    def test_sphinx_wins(self):
        shutil.copy(os.path.join(self.site, "objects.inv"), self.dox)
        code, out, err = self.run_main("detect", self.dox)
        self.assertIn("type: sphinx\n", out)
        self.assertIn("also: doxygen", out)

    def test_build_search(self):
        code, out, err = self.run_main("build", self.dox, "--name", "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("index: search", out)
        entries = self.entries()
        self.assertIn({"name": "doThing", "type": "Function", "path": "group__demo#ga0"}, entries)
        self.assertIn({"name": "Guide page", "type": "Guide", "path": "guide"}, entries)
        db = load(self.docvol, "db.json")
        self.assertIn("Thing doc", db["group__demo"])
        self.assertNotIn("Long prose", db["guide"])
        self.assertEqual(load_plan(self.plan_path)["index"], "search")

    def test_rebuild_sees_changed_index(self):
        self.assertEqual(self.run_main("build", self.dox, "--name", "demo")[0], 0)
        write(self.dox, "search/functions_0.js", doxy_fn_js("doThing", "doMore"))
        code, out, err = self.run_main("build", "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("the inventory changed", out)
        self.assertIn({"name": "doMore", "type": "Function", "path": "group__demo#ga1"}, self.entries())

    def test_build_menu(self):
        menu = os.path.join(self.tmp, "menu")
        write(menu, "menudata.js", 'var menudata={children:[{text:"Functions",url:"globals_func.html"}]}')
        write(menu, "globals_func.html", doxy_page(
            '<ul><li>doThing()\n: <a class="el" href="demo_8h.html#a1">demo.h</a>\n</li></ul>'))
        write(menu, "demo_8h.html", doxy_page('<a id="a1"></a><h2 class="memtitle">doThing()</h2><p>T</p>'))
        code, out, err = self.run_main("build", menu, "--name", "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("index: menu", out)
        self.assertIn({"name": "doThing", "type": "Function", "path": "demo_8h#a1"}, self.entries())

    def test_neither(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        code, _, err = self.run_main("plan", empty, "--name", "demo")
        self.assertNotEqual(code, 0)
        self.assertIn("objects.inv", err)


if __name__ == "__main__":
    unittest.main()
