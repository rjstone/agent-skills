"""Offline tests for skills/docshelf-build. No network: inventories are made
by make_inv() and sites are folders or fake openers. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO_ROOT, "skills", "docshelf-build")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import build_core  # noqa: E402
from build_core import CLIError  # noqa: E402
from build_inventory import InvEntry, parse_inventory, page_key, split_uri  # noqa: E402
from build_plan import load_plan, make_plan, save_plan, summarize  # noqa: E402
import build_fetch  # noqa: E402
from build_fetch import fetch_pages, normalize_source, open_source  # noqa: E402
from build_html import main_content, rewrite_links, stub_html  # noqa: E402
from build_docvol import check_name, derive_name, role_label, write_docvol  # noqa: E402
import docshelf_build  # noqa: E402

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
        self.assertEqual(meta["slug"], "demo")
        self.assertEqual(meta["source"], SRC)
        self.assertEqual(meta["inventory_sha256"], "abc")
        self.assertEqual(meta["entry_count"], len(idx["entries"]))
        self.assertEqual(sorted(os.listdir(self.folder)), ["db.json", "index.json", "meta.json"])

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


if __name__ == "__main__":
    unittest.main()
