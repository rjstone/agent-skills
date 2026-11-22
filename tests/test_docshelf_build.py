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
        with mock.patch("urllib.request.urlopen", fake_urlopen):
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
          + "\n\n```\n" + "".join("--flag%d VALUE\n" % i for i in range(12)) + "```\n")
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
        self.assertEqual(RULES_ID, "model:rules-1")

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

    def test_fixture_agreement_per_site(self):
        with open(os.path.join(HERE, "fixtures", "docshelf_build_classify.json")) as f:
            data = json.load(f)
        for site in ("langchain", "opencode"):
            pages = [p for p in data["pages"] if p["site"] == site]
            decided = [(rule_choice(p["signals"]), p["label"]) for p in pages]
            decided = [(c, lab) for c, lab in decided if c != "review"]
            agree = sum((c == "full") == (lab == "reference") for c, lab in decided)
            self.assertGreaterEqual(agree / max(1, len(decided)), 0.95, site)
            self.assertGreater(len(decided), 0, site)


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
                         ["model:rules-1", "model:rules-1", "llms: all"])
        before = json.loads(json.dumps(plan))
        run_rules(plan)
        self.assertEqual(plan, before)

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


if __name__ == "__main__":
    unittest.main()
