"""Offline tests for skills/docshelf. No network: docsets are built by
make_devdocs() in temp dirs. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("docshelf"):
    raise unittest.SkipTest("docshelf not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO_ROOT, "skills", "docshelf")
SCRIPT = os.path.join(SKILL, "scripts", "docshelf.py")

sys.path.insert(0, os.path.join(SKILL, "scripts"))
import shelf_cli  # noqa: E402
from shelf_core import CLIError  # noqa: E402
import shelf_core  # noqa: E402
import shelf_devdocs  # noqa: E402
import shelf_lookup  # noqa: E402
import shelf_notes  # noqa: E402
import shelf_render  # noqa: E402

LEAKY_ENV = ("DOCSHELF_CACHE_DIR", "DOCSHELF_NOTES_DIR", "APPDATA",
             "LOCALAPPDATA", "OLDPWD")


def clean_env():
    """os.environ without variables that would leak the real cache or notes."""
    return {k: v for k, v in os.environ.items()
            if k not in LEAKY_ENV and not k.startswith("XDG_")}


def run_cli(*args, env=None, cwd=None, script=SCRIPT):
    full_env = clean_env()
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, script, *args], capture_output=True,
                          text=True, env=full_env, cwd=cwd)


def make_devdocs(cache: str, slug: str, *, name: str, release: str,
                 entries: List[Tuple[str, str, str]], pages: Dict[str, str],
                 alias: Optional[str] = None, mtime: int = 1700000000,
                 version: Optional[str] = None) -> str:
    """Write <cache>/devdocs/<slug>/{index.json, db.json, meta.json} and append
    the manifest row to <cache>/devdocs/docs.json; return the docset folder.

    entries are (name, type, path) tuples; pages maps path -> HTML."""
    root = os.path.join(cache, "devdocs")
    folder = os.path.join(root, slug)
    os.makedirs(folder, exist_ok=True)
    types = sorted({t for _, t, _ in entries})
    index = {"entries": [{"name": n, "type": t, "path": p} for n, t, p in entries],
             "types": [{"name": t, "count": sum(1 for e in entries if e[1] == t),
                        "slug": t.lower().replace(" ", "_")} for t in types]}

    def dump(path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)  # real db.json is raw UTF-8

    dump(os.path.join(folder, "index.json"), index)
    dump(os.path.join(folder, "db.json"), pages)
    dump(os.path.join(folder, "meta.json"),
         {"slug": slug, "name": name, "release": release, "mtime": mtime,
          "installedAt": "2026-11-16T00:00:00Z", "alias": alias,
          **({"version": version} if version else {})})
    manifest_path = os.path.join(root, "docs.json")
    manifest = []
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    manifest.append({
        "name": name, "slug": slug, "type": slug.split("~")[0],
        "version": version if version is not None else
        (slug.split("~", 1)[1].replace("_", " ") if "~" in slug else ""),
        "release": release, "mtime": mtime,
        "db_size": os.path.getsize(os.path.join(folder, "db.json")),
        "attribution": "", "alias": alias, "links": {}})
    dump(manifest_path, manifest)
    return folder


class SkeletonTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.home = os.path.join(self.tmp, "home")
        self.cache = os.path.join(self.tmp, "cache")
        self.notes = os.path.join(self.tmp, "notes")
        self.work = os.path.join(self.tmp, "work")
        for d in (self.home, self.work):
            os.makedirs(d)

    def env(self, **extra):
        env = {"HOME": self.home, "USERPROFILE": self.home,
               "DOCSHELF_CACHE_DIR": self.cache, "DOCSHELF_NOTES_DIR": self.notes}
        env.update(extra)
        return env

    def test_help_runs(self):
        r = run_cli("--help", env=self.env(), cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("docshelf 0.1.0"), r.stdout)
        self.assertIn("where", r.stdout)

    def test_no_command_exits_2(self):
        self.assertEqual(run_cli(env=self.env(), cwd=self.work).returncode, 2)

    def test_where_defaults(self):
        env = {"HOME": self.home, "USERPROFILE": self.home}
        r = run_cli("where", env=env, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cache: %s (default)" % os.path.join(self.home, ".cache", "docshelf"),
                      r.stdout)
        self.assertIn("notes: %s (default)" % os.path.join(
            self.home, ".local", "share", "docshelf", "notes"), r.stdout)
        self.assertIn("project: none", r.stdout)

    def test_where_env(self):
        r = run_cli("where", env=self.env(), cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cache: %s (DOCSHELF_CACHE_DIR)" % self.cache, r.stdout)
        self.assertIn("notes: %s (DOCSHELF_NOTES_DIR)" % self.notes, r.stdout)

    def test_project_file_found_from_skill_folder(self):
        proj = os.path.join(self.home, "proj")
        os.makedirs(proj)
        with open(os.path.join(proj, ".docshelf.json"), "w") as f:
            json.dump({"docsets": ["python~3.12"]}, f)
        r = run_cli("where", env=self.env(OLDPWD=proj), cwd=SKILL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("project: %s" % os.path.join(proj, ".docshelf.json"), r.stdout)
        self.assertIn("OLDPWD", r.stderr)

    def test_bad_project_docsets(self):
        with open(os.path.join(self.work, ".docshelf.json"), "w") as f:
            json.dump({"docsets": "x"}, f)
        r = run_cli("where", env=self.env(), cwd=self.work)
        self.assertEqual(r.returncode, 2)
        self.assertIn(".docshelf.json", r.stderr)

    def test_load_config_reads_docsets(self):
        with open(os.path.join(self.work, ".docshelf.json"), "w") as f:
            json.dump({"docsets": ["a", "b~1"]}, f)
        cfg = shelf_core.load_config(self.work, self.env())
        self.assertEqual(cfg.project_docsets, ["a", "b~1"])
        self.assertEqual(cfg.cache_source, "env")


class ProjectFileFallbackTests(unittest.TestCase):
    """Where .docshelf.json is looked for when the current folder has none
    (agents often cd into the skill folder before running the script)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.home, "work", "proj")
        self.sub = os.path.join(self.proj, "a", "b")
        self.other = os.path.join(self.tmp, "other")
        for d in (self.sub, self.other):
            os.makedirs(d)
        self.env = {"HOME": self.home, "USERPROFILE": self.home,
                    "DOCSHELF_CACHE_DIR": os.path.join(self.tmp, "cache"),
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def project(self, folder, docsets=("x",)):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, ".docshelf.json"), "w") as f:
            json.dump({"docsets": list(docsets)}, f)

    def script_copy(self, skill_dir):
        """A copy of the scripts at <skill_dir>/scripts/."""
        dest = os.path.join(skill_dir, "scripts")
        shutil.copytree(os.path.dirname(SCRIPT), dest,
                        ignore=shutil.ignore_patterns("__pycache__"))
        return os.path.join(dest, "docshelf.py")

    def where(self, script=SCRIPT, *, cwd, **env):
        return run_cli("where", env=dict(self.env, **env), cwd=cwd, script=script)

    def test_found_from_oldpwd(self):
        self.project(self.proj)
        r = self.where(cwd=self.other, OLDPWD=self.sub)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("project: " + os.path.join(self.proj, ".docshelf.json"), r.stdout)
        # says which file it used and why, since it isn't under the current folder
        self.assertIn(os.path.join(self.proj, ".docshelf.json"), r.stderr)
        self.assertIn("OLDPWD", r.stderr)

    def test_found_from_script_folder(self):
        self.project(self.proj)
        script = self.script_copy(os.path.join(self.proj, ".claude", "skills", "docshelf"))
        r = self.where(script, cwd=self.other)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("project: " + os.path.join(self.proj, ".docshelf.json"), r.stdout)
        self.assertIn("script", r.stderr)

    def test_current_folder_wins_and_prints_no_note(self):
        self.project(self.proj)
        elsewhere = os.path.join(self.home, "elsewhere")
        self.project(elsewhere)
        r = self.where(cwd=self.sub, OLDPWD=elsewhere)
        self.assertIn("project: " + os.path.join(self.proj, ".docshelf.json"), r.stdout)
        self.assertEqual(r.stderr, "")

    def test_script_folder_before_oldpwd(self):
        self.project(self.proj)
        script = self.script_copy(os.path.join(self.proj, "skills", "docshelf"))
        elsewhere = os.path.join(self.home, "elsewhere")
        self.project(elsewhere)
        r = self.where(script, cwd=self.other, OLDPWD=elsewhere)
        self.assertIn("project: " + os.path.join(self.proj, ".docshelf.json"), r.stdout)

    def test_fallback_walk_checks_home_then_stops(self):
        # the home folder itself is checked ...
        self.project(self.home)
        r = self.where(cwd=self.other, OLDPWD=self.sub)
        self.assertIn("project: " + os.path.join(self.home, ".docshelf.json"), r.stdout)
        # ... but nothing above it
        os.remove(os.path.join(self.home, ".docshelf.json"))
        self.project(self.tmp)
        outside = tempfile.TemporaryDirectory()  # not under self.tmp
        self.addCleanup(outside.cleanup)
        r = self.where(cwd=outside.name, OLDPWD=self.sub)
        self.assertIn("project: none", r.stdout)

    def test_walk_up_stops_below_users_folders(self):
        w = shelf_core.walk_up
        env = {"HOME": os.path.join(os.sep, "home", "me")}
        self.assertEqual(list(w(os.path.join(os.sep, "home", "me", "p", "q"), env)),
                         [os.path.join(os.sep, "home", "me", "p", "q"),
                          os.path.join(os.sep, "home", "me", "p"),
                          os.path.join(os.sep, "home", "me")])
        # someone else's home: stop before /home; never the filesystem root
        self.assertEqual(list(w(os.path.join(os.sep, "home", "you", "p"), env)),
                         [os.path.join(os.sep, "home", "you", "p"),
                          os.path.join(os.sep, "home", "you")])
        self.assertEqual(list(w(os.path.join(os.sep, "Users", "you"), env)),
                         [os.path.join(os.sep, "Users", "you")])


class DevDocsDiskTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work)
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def cfg(self):
        return shelf_core.load_config(self.work, self.env)

    def make(self, slug="vite", **kw):
        kw.setdefault("name", "Vite")
        kw.setdefault("release", "5")
        kw.setdefault("entries", [("Guide", "Guide", "guide")])
        kw.setdefault("pages", {"guide": "<p>hi</p>"})
        return make_devdocs(self.cache, slug, **kw)

    def test_page_spans_exact(self):
        pages = {"a/b": "\u00e9 \u2603 \" \\ </p>", "big": "x" * 2048,
                 "tail\\": "\\", "q": "\"", "u": "\U0001F600 \n\t"}
        folder = self.make(pages=pages,
                           entries=[("A", "T", k) for k in pages])
        db = os.path.join(folder, "db.json")
        with open(db, "rb") as f:
            self.assertIn("\u2603".encode("utf-8"), f.read())  # raw UTF-8
        idx = shelf_devdocs.build_page_index(db)
        with open(db, encoding="utf-8") as f:
            expected = json.load(f)
        self.assertEqual(set(idx), set(expected))
        for key in expected:
            self.assertEqual(shelf_devdocs.read_span(db, idx[key]), expected[key])

    def test_index_rebuilt_when_db_changes(self):
        folder = self.make()
        d = shelf_devdocs.installed_docsets(self.cfg())[0]
        self.assertEqual(d.page_html("guide"), "<p>hi</p>")
        db = os.path.join(folder, "db.json")
        with open(db, "w", encoding="utf-8") as f:
            json.dump({"guide": "<p>new text</p>"}, f, ensure_ascii=False)
        os.utime(db, (1800000000, 1800000000))
        d2 = shelf_devdocs.installed_docsets(self.cfg())[0]
        self.assertEqual(d2.page_html("guide"), "<p>new text</p>")
        self.assertEqual(d.page_html("guide"), "<p>new text</p>")  # same object too

    def test_works_without_derived_dir(self):
        folder = self.make()
        d = shelf_devdocs.installed_docsets(self.cfg())[0]
        d.page_html("guide")
        derived = os.path.join(folder, ".docshelf")
        shutil.rmtree(derived)
        d2 = shelf_devdocs.installed_docsets(self.cfg())[0]
        self.assertEqual(d2.page_html("guide"), "<p>hi</p>")
        self.assertTrue(os.path.isfile(os.path.join(derived, "pages.json")))

    def test_entries_and_resolve(self):
        self.make(entries=[("Guide", "Guide", "guide"),
                           ("Sec", "Guide", "guide#sec")],
                  pages={"guide": "<p>x</p>"})
        d = shelf_devdocs.installed_docsets(self.cfg())[0]
        e = d.entries()[1]
        self.assertEqual((e.ref, e.page, e.anchor), ("vite:guide#sec", "guide", "sec"))
        page, anchor, entry = d.resolve("guide#sec")
        self.assertEqual((page, anchor, entry), ("guide", "sec", e))
        self.assertIsNone(d.resolve("guide#nope")[2])
        self.assertEqual(d.make_ref("guide", "sec"), "vite:guide#sec")
        self.assertEqual(d.stamp(), "1700000000|%d" % os.path.getsize(
            os.path.join(d.folder, "db.json")))
        with self.assertRaises(shelf_core.CLIError) as cm:
            d.page_html("missing")
        self.assertEqual(cm.exception.code, 5)

    def test_installed_sorted_and_skips_broken(self):
        self.make("zed", name="Zed")
        self.make("alpha", name="Alpha")
        os.makedirs(os.path.join(self.cache, "devdocs", "broken"))
        names = [d.name for d in shelf_devdocs.installed_docsets(self.cfg())]
        self.assertEqual(names, ["alpha", "zed"])

    def test_list(self):
        r = run_cli("list", env=self.env, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         "no docsets installed (install NAME; sources QUERY finds names)")
        self.make("vite", name="Vite", release="5")
        big = {"p%d" % i: "x" for i in range(500)}
        self.make("big~2", name="Big", release="2",
                  entries=[("E%d" % i, "T", k) for i, k in enumerate(big)],
                  pages=big)
        r = run_cli("list", env=self.env, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "big~2  Big  2  500 entries  full",
            "vite  Vite  5  1 entries  small"])

    def test_pick_family_ambiguous(self):
        self.make("python~3.13", name="Python", release="3.13.8", alias="py")
        self.make("python~3.14", name="Python", release="3.14.8", alias="py")
        self.make("vite")
        self.make("node~24_lts", name="Node.js", release="24.14.0")
        self.make("ruby~3.4", name="Ruby", release="3.4.1", version="3.4 x")
        ds = shelf_devdocs.installed_docsets(self.cfg())
        for q in ("python", "py"):
            with self.assertRaises(shelf_core.CLIError) as cm:
                shelf_core.pick_docset(ds, q)
            self.assertEqual(cm.exception.code, 2)
            self.assertIn("python~3.13", str(cm.exception))
            self.assertIn("python~3.14", str(cm.exception))
        self.assertEqual(shelf_core.pick_docset(ds, "Python 3.14").name, "python~3.14")
        self.assertEqual(shelf_core.pick_docset(ds, "VITE").name, "vite")
        self.assertEqual(shelf_core.pick_docset(ds, "Vite").title, "Vite")
        self.assertEqual(shelf_core.pick_docset(ds, "Node.js 24 LTS").name, "node~24_lts")
        self.assertEqual(shelf_core.pick_docset(ds, "Ruby 3.4 x").name, "ruby~3.4")
        with self.assertRaises(shelf_core.CLIError) as cm:
            shelf_core.pick_docset(ds, "nope")
        self.assertEqual(cm.exception.code, 5)
        with self.assertRaises(shelf_core.ScopeError):
            shelf_core.select_docsets(self.cfg(), ds, ["nope"], False)
        self.assertEqual(len(shelf_core.select_docsets(self.cfg(), ds, [], False)), 5)


class RenderTests(unittest.TestCase):
    def text(self, html, **kw):
        return [b.text for b in shelf_render.html_to_text(html, **kw)]

    def test_headings_lists_pre(self):
        html = ("<h1 id='t'>Title</h1><p>Body  text\n here</p><ul><li>a</li><li>b</li></ul>"
                "<pre>x = 1\n  y = 2\n</pre>")
        self.assertEqual(self.text(html), ["# Title", "Body text here", "- a", "- b",
                                           "```\nx = 1\n  y = 2\n```"])

    def test_no_link_suffix_in_pre_or_headings(self):
        html = ("<h2 id='h'>See <a href='x'>x</a></h2><pre>a <a href='x'>x</a> b</pre>"
                "<p>go <a href='x'>x</a></p>")
        out = self.text(html, link=lambda h: "d:" + h)
        self.assertEqual(out, ["## See x", "```\na x b\n```", "go x [d:x]"])

    def test_navigation_chrome_dropped(self):
        html = ('<div class="related" role="navigation"><h3>Navigation</h3>'
                '<ul><li>index</li><li><div>nested</div></li></ul></div>'
                '<div class="mobile-nav"><form><input></form>'
                '<select><option>Dark</option></select></div>'
                '<div role="main"><h1 id="t">Title<a class="headerlink">¶</a></h1>'
                '<p>Body</p></div><div role="search">Quick search</div>')
        self.assertEqual(self.text(html), ["# Title", "Body"])

    def test_colspan_cells_labelled(self):
        html = ("<table><tr><td>31</td><td>30</td><td>29</td></tr>"
                "<tr><td>1</td><td colspan='2'>Rm</td></tr>"
                "<tr><td colspan='3'></td></tr></table>")
        text = self.text(html)
        self.assertIn("1 | Rm (2 cols)", text)
        self.assertFalse(any("cols" in t and "Rm" not in t for t in text))

    def test_hidden_div_dropped(self):
        html = ('<div style="display:none;" hidden data-nosnippet>Are you an LLM? '
                'Read the .md version.</div><h1>Vite</h1><p>Body</p><input hidden>'
                '<p>After</p>')
        self.assertEqual(self.text(html), ["# Vite", "Body", "After"])

    def test_pre_language(self):
        html = '<pre data-language="js">const a = 1\n</pre><pre>plain</pre>'
        self.assertEqual(self.text(html), ["```js\nconst a = 1\n```", "```\nplain\n```"])

    def test_link_to_ref(self):
        seen = []

        def link(href):
            seen.append(href)
            return "vite:api/foo#bar" if href == "../api/foo#bar" else None

        html = ('<p>See <a href="../api/foo#bar">foo</a>, <a href="#top">top</a>, '
                '<a href="https://x.org/">ext</a>, <a href="../other">other</a>.</p>')
        self.assertEqual(self.text(html, link=link),
                         ["See foo [vite:api/foo#bar], top, ext, other."])
        self.assertEqual(seen, ["../api/foo#bar", "../other"])

    def test_no_link_callback(self):
        self.assertEqual(self.text('<p><a href="x">y</a></p>'), ["y"])

    def test_page_title(self):
        blocks = shelf_render.html_to_text("<h2>Sub</h2><h1>Top</h1><h1>Two</h1>")
        self.assertEqual(shelf_render.page_title(blocks), "Top")
        self.assertIsNone(shelf_render.page_title(shelf_render.html_to_text("<p>x</p>")))

    def test_section_lines_by_anchor(self):
        html = ("<h1>P</h1><h2 id='a'>A</h2><p>one</p><h3>A1</h3><p>two</p>"
                "<h2 id='b'>B</h2><p>three</p>")
        blocks = shelf_render.html_to_text(html)
        lines, _ = shelf_render.section_lines(blocks, "a")
        self.assertEqual(lines, ["## A", "one", "### A1", "two"])
        lines, _ = shelf_render.section_lines(blocks, "zz")
        self.assertTrue(lines[0].startswith("note: anchor not found (zz)"))
        self.assertEqual(len(shelf_render.section_lines(blocks, None)[0]), 7)


class RenderGrepTests(unittest.TestCase):
    PAGE = ("<h2 id='params'>Parameters</h2><p>Options for read_csv.</p>"
            "<table><tr><th>Name</th><th>Type</th><th>Default</th></tr>"
            "<tr><td>header</td><td>BOOL</td><td>false</td></tr>"
            "<tr><td>sep</td><td>VARCHAR</td><td>,</td></tr>"
            "<tr><td>skip</td><td>BIGINT</td><td>0</td></tr>"
            "<tr><td>quote</td><td>VARCHAR</td><td>\"</td></tr></table>"
            "<p>Use SKIP to ignore leading lines.</p>")

    def lines(self, html):
        return shelf_render.section_lines(shelf_render.html_to_text(html), None)

    def test_grep_keeps_heading_table_header_and_matches(self):
        lines, ends = self.lines(self.PAGE)
        out = shelf_render.grep_lines(lines, ["skip"], ends)
        self.assertEqual(out[0], "## Parameters")
        row = next(k for k, l in enumerate(out) if "BIGINT" in l)
        self.assertIn("Name", out[row - 2])
        self.assertEqual(out[row - 1], "...")
        self.assertIn("Use SKIP to ignore leading lines.", out)
        self.assertFalse(any("VARCHAR" in l or "Options" in l for l in out))

    DL = ("<h2 id='f'>read_csv</h2><dl><dt id='sig'>read_csv(path, on_bad_lines='error')</dt>"
          "<dd><p>Read a file.</p><dl>"
          "<dt><strong>on_bad_lines</strong> str</dt>"
          "<dd><p>What to do with a bad line.</p><ul><li>'error', raise.</li></ul></dd>"
          "<dt><strong>low_memory</strong> bool</dt><dd><p>Chunks.</p></dd>"
          "<dt><strong>long_one</strong> str</dt><dd>"
          + "".join("<p>long line %d</p>" % i for i in range(60))
          + "</dd></dl></dd></dl>")

    def test_definition_term_shows_its_definition(self):
        lines, ends = self.lines(self.DL)
        out = shelf_render.grep_lines(lines, ["on_bad_lines"], ends)
        self.assertIn("What to do with a bad line.", out)
        self.assertIn("- 'error', raise.", out)
        self.assertNotIn("Chunks.", out)
        self.assertNotIn("Read a file.", out)

    def test_long_definition_not_added(self):
        lines, ends = self.lines(self.DL)
        out = shelf_render.grep_lines(lines, ["long_one"], ends)
        self.assertFalse(any("long line" in l for l in out))


class RankTests(unittest.TestCase):
    def test_rank_order(self):
        r = shelf_core.rank
        self.assertEqual(r("Gather", "gather"), 0)
        self.assertEqual(r("gat", "Gather"), 1)
        self.assertEqual(r("ath", "Gather"), 2)
        self.assertEqual(r("gtr", "Gather"), 3)
        self.assertIsNone(r("xyz", "Gather"))
        self.assertIsNone(r("rg", "Gather"))  # order matters

    def test_cap_lines(self):
        lines = ["l%d" % i for i in range(10)]
        self.assertEqual(shelf_core.cap_lines(lines, 10, "h"), lines)
        out = shelf_core.cap_lines(lines, 4, "use --x")
        self.assertEqual(out[:4], lines[:4])
        self.assertEqual(out[4], "... 6 more lines cut; use --x")
        self.assertEqual(len(out), 5)

    def test_short_name(self):
        self.assertEqual(shelf_core.short_name("Foo(a, [b])"), "foo")
        self.assertEqual(shelf_core.short_name("(x)"), "(x)")


class SearchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def add(self, slug, entries=None, name=None):
        entries = entries if entries is not None else [("x", "Function", "x")]
        pages = {e[2].partition("#")[0]: "<p>t</p>" for e in entries}
        make_devdocs(self.cache, slug, name=name or slug.capitalize(),
                     release="1", entries=entries, pages=pages)

    def cli(self, *args, project=None):
        if project is not None:
            with open(os.path.join(self.tmp, ".docshelf.json"), "w") as f:
                json.dump(project, f)
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def test_several_names_at_once_lists_the_best_entry_for_each_word(self):
        self.add("alpha", [("date_diff(part, a, b)", "Function", "date#diff"),
                           ("date_diff_old", "Function", "date#old"),
                           ("date_sub(part, a, b)", "Function", "date#sub")])
        r = self.cli("search", "date_diff", "date_sub", "zzz", "-d", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertIn("one entry name", out[0])
        self.assertIn("'date_diff date_sub zzz'", out[0])
        self.assertIn("alpha:date#diff  Function  date_diff(part, a, b)", out)
        self.assertIn("alpha:date#sub  Function  date_sub(part, a, b)", out)
        self.assertNotIn("date_diff_old", r.stdout)
        self.assertTrue(any("'zzz'" in l and "no entry name" in l for l in out), out)

    def test_several_words_none_in_any_name_keeps_the_plain_message(self):
        self.add("alpha", [("date_sub", "Function", "date#sub")])
        r = self.cli("search", "enemy", "arrow", "-d", "alpha")
        self.assertTrue(r.stdout.startswith(
            "no matches for 'enemy arrow' (entry names only"), r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 1)

    def test_docset_name_is_case_insensitive(self):
        self.add("alpha", [("date_sub", "Function", "date#sub")])
        r = self.cli("search", "date_sub", "-d", "ALPHA")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha:date#sub", r.stdout)
        r = self.cli("search", "date_sub", project={"docsets": ["Alpha"]})
        self.assertIn("alpha:date#sub", r.stdout)

    def test_anchored_signature_beats_bare_page_entry(self):
        self.add("alpha", [("date_sub", "Function", "date"),
                           ("date_sub(part, a, b)", "Function", "date#sub"),
                           ("date_subx", "Function", "date#x")])
        out = self.cli("search", "date_sub", "-d", "alpha").stdout.splitlines()
        names = [l.split("  ")[2] for l in out]
        self.assertEqual(names, ["date_sub(part, a, b)", "date_subx"])
        self.assertNotIn("alpha:date  ", "\n".join(out))

    def test_bare_entry_kept_when_no_anchored_twin_on_its_page(self):
        self.add("alpha", [("date_sub", "Function", "other"),
                           ("date_sub(part, a, b)", "Function", "date#sub")])
        out = self.cli("search", "date_sub", "-d", "alpha").stdout.splitlines()
        self.assertEqual([l.split("  ")[2] for l in out],
                         ["date_sub(part, a, b)", "date_sub"])
        r = self.cli("search", "date_sub", "-d", "alpha", "--json")
        self.assertEqual(len(json.loads(r.stdout)), 2)

    def test_folded_entries_in_json(self):
        self.add("alpha", [("date_sub", "Function", "date"),
                           ("date_sub(part, a, b)", "Function", "date#sub")])
        items = json.loads(self.cli("search", "date_sub", "-d", "alpha",
                                    "--json").stdout)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["same_section"], ["alpha:date"])

    def test_multi_word_queries(self):
        self.add("alpha", [("hero:get_walking_speed()", "Method", "a"),
                           ("hero:set_walking_speed(speed)", "Method", "a"),
                           ("walking", "Guide", "b")])
        r = self.cli("search", "walking", "speed", "-d", "alpha")  # unquoted
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(len(out), 2, out)
        self.assertTrue(all("walking_speed" in l for l in out))
        r = self.cli("search", "speed walking", "-d", "alpha")  # any word order
        self.assertEqual(len(r.stdout.splitlines()), 2)

    def test_fuzzy_hits_capped_when_real_hits_exist(self):
        entries = [("timer", "Function", "a")] + [
            ("t_i_m_e_r_%d" % n, "Function", "a") for n in range(9)]
        self.add("alpha", entries)
        out = self.cli("search", "timer", "-d", "alpha").stdout.splitlines()
        self.assertEqual(out, ["alpha:a  Function  timer"])
        self.add("beta", [("timers", "Function", "a")] + entries[1:])
        r = self.cli("search", "timer", "-d", "beta")  # no whole-word hit
        self.assertEqual(r.stdout.splitlines()[-1], "... 9 fuzzy matches hidden "
                         "(letters in order only, often unrelated)")
        self.add("gamma", [("asyncio.gather", "Function", "a"),
                           ("g_a_t_h_e_r", "Function", "a#x")])
        r = self.cli("search", "gather", "-d", "gamma")
        self.assertEqual(r.stdout.splitlines(),
                         ["gamma:a  Function  asyncio.gather"])
        r = self.cli("search", "tmr", "-d", "alpha")  # only fuzzy: none cut
        self.assertEqual(sum(1 for l in r.stdout.splitlines()
                             if "t_i_m_e_r" in l), 9)

    def test_search_ranks_across_docsets(self):
        self.add("alpha", [("sleep_long", "Function", "a"),
                           ("sleep", "Function", "b")])
        self.add("beta", [("Sleep", "Guide", "c"), ("xsleepx", "Guide", "d"),
                          ("s_l_e_e_p", "Guide", "e")])
        r = self.cli("search", "sleep")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(len(out), 4, out)
        names = [l.split("  ")[2] for l in out]
        self.assertEqual(names, ["Sleep", "sleep", "sleep_long", "xsleepx"])
        r = self.cli("search", "slp", "-d", "alpha")
        self.assertTrue(r.stdout.startswith("no exact, prefix or substring matches"))
        r = self.cli("search", "qqq", "-d", "alpha")
        self.assertTrue(r.stdout.startswith("no matches for 'qqq' (entry names only"))
        self.assertEqual(out[0].split("  ")[:2], ["beta:c", "Guide"])
        self.assertTrue(out[1].startswith("alpha:b  "))

    def test_search_type_filter_case_insensitive(self):
        self.add("alpha", [("sleep", "Function", "a"), ("sleep2", "Guide", "b")])
        r = self.cli("search", "sleep", "--type", "guide")
        self.assertEqual(len(r.stdout.splitlines()), 1)
        self.assertIn("sleep2", r.stdout)

    def test_search_special_characters_are_literal(self):
        self.add("alpha", [("a_c", "Function", "a"), ("abc", "Function", "b"),
                           ("100%", "Function", "c")])
        r = self.cli("search", "a_c")
        self.assertEqual([l.split("  ")[2] for l in r.stdout.splitlines()], ["a_c"])
        r = self.cli("search", "%")
        self.assertEqual([l.split("  ")[2] for l in r.stdout.splitlines()], ["100%"])

    def test_unknown_docset_exits_4(self):
        self.add("alpha")
        r = self.cli("search", "x", "-d", "Nope")
        self.assertEqual(r.returncode, 4)
        self.assertIn("Nope", r.stderr)

    def test_scope_names_beat_project(self):
        self.add("alpha", [("thing", "Function", "a")])
        self.add("beta", [("thing", "Function", "b")])
        r = self.cli("search", "thing", "-d", "beta",
                     project={"docsets": ["alpha"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("beta:", r.stdout)
        self.assertNotIn("alpha:", r.stdout)

    def test_scope_project_list(self):
        for n in "abcdef":
            self.add("doc" + n, [("thing", "Function", "a")])
        r = self.cli("search", "thing", project={"docsets": ["docb", "docc"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(l.split(":")[0] for l in r.stdout.splitlines()),
                         ["docb", "docc"])

    def test_scope_error_over_four_full(self):
        big = [("thing", "Function", "a")] + [
            ("f%d" % i, "Function", "p%d" % i) for i in range(500)]
        for n in "abcde":
            self.add("doc" + n, big)
        r = self.cli("search", "thing")
        self.assertEqual(r.returncode, 4)
        for n in "abcde":
            self.assertIn("doc" + n, r.stderr)
        for hint in ("-d", "docsets", ".docshelf.json", "--all"):
            self.assertIn(hint, r.stderr)
        r = self.cli("search", "thing", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 5)

    def test_scope_small_docsets_dont_count(self):
        big = [("thing", "Function", "a")] + [
            ("f%d" % i, "Function", "p%d" % i) for i in range(500)]
        for n in "abcd":
            self.add("doc" + n, big)
        for n in "xyz":
            self.add("small" + n, [("thing", "Function", "a")])
        r = self.cli("search", "thing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 7)

    def test_search_max_lines_and_hint(self):
        self.add("alpha", [("item%02d" % i, "Function", "p%d" % i)
                           for i in range(50)])
        lines = self.cli("search", "item").stdout.splitlines()
        self.assertEqual(len(lines), 41)
        self.assertTrue(lines[-1].startswith("... 10 more lines cut;"), lines[-1])
        self.assertIn("--max-lines", lines[-1])
        r = self.cli("search", "item", "--max-lines", "5")
        self.assertEqual(len(r.stdout.splitlines()), 6)

    def test_search_json(self):
        self.add("alpha", [("sleep", "Function", "a"), ("sleeper", "Guide", "b")])
        r = self.cli("search", "sleep", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual([d["name"] for d in data], ["sleep", "sleeper"])
        self.assertEqual(set(data[0]), {"ref", "docset", "type", "name", "rank"})
        self.assertEqual((data[0]["docset"], data[0]["rank"], data[1]["rank"]),
                         ("alpha", 0, 1))
        self.assertEqual(data[0]["ref"], "alpha:a")
        r = self.cli("search", "sleep", "--json", "--max-lines", "1")
        self.assertEqual(len(json.loads(r.stdout)), 1)

    def test_empty_query_exits_2(self):
        self.add("alpha")
        r = self.cli("search", " ")
        self.assertEqual(r.returncode, 2)


class ShowTests(unittest.TestCase):
    PY_PAGE = ("<h1>Asyncio</h1><h2 id='asyncio.gather'>asyncio.gather</h2>"
               "<p>Run awaitables concurrently.</p><pre>await asyncio.gather(a(), b())</pre>"
               "<h2 id='asyncio.sleep'>asyncio.sleep</h2><p>Block for a while.</p>")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def add(self, slug, entries, pages, name=None):
        make_devdocs(self.cache, slug, name=name or slug.capitalize(),
                     release="1", entries=entries, pages=pages)

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def add_py(self):
        self.add("py", [("asyncio.gather", "Function", "a#asyncio.gather"),
                        ("asyncio.sleep", "Function", "a#asyncio.sleep"),
                        ("Guide", "Guide", "guide")],
                 {"a": self.PY_PAGE, "guide": "<h1>Guide</h1><p>Gather things.</p>"})

    def test_show_trims_to_anchor(self):
        self.add_py()
        r = self.cli("show", "py:a#asyncio.gather")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Run awaitables concurrently.", r.stdout)
        self.assertIn("await asyncio.gather(a(), b())", r.stdout)
        self.assertNotIn("Block for", r.stdout)
        r = self.cli("show", "py:guide")  # no anchor: whole page
        self.assertIn("# Guide", r.stdout)
        r = self.cli("show", "py:a#asyncio.gather", "--full", "--no-notes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Block for", r.stdout)

    def test_show_full_lifts_cap_on_long_section(self):
        body = "".join("<p>row %d</p>" % i for i in range(300))
        self.add("l", [("sec", "Section", "p#s")],
                 {"p": "<h2 id='s'>Sec</h2>" + body + "<h2 id='t'>Next</h2><p>other</p>"})
        r = self.cli("show", "l:p#s")
        self.assertEqual(len(r.stdout.splitlines()), 151)
        self.assertIn("--full", r.stdout.splitlines()[-1])
        r = self.cli("show", "l:p#s", "--max-lines", "10")
        self.assertEqual(len(r.stdout.splitlines()), 11)
        r = self.cli("show", "l:p#s", "--full")
        self.assertEqual(len(r.stdout.splitlines()), 301)
        self.assertNotIn("other", r.stdout)

    def test_ref_path_with_colon(self):
        self.add("cpp", [("std::vector", "Class", "cpp/container/vector#std::vector")],
                 {"cpp/container/vector": "<h2 id='std::vector'>std::vector</h2><p>dyn array</p>"})
        r = self.cli("show", "cpp:cpp/container/vector#std::vector")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dyn array", r.stdout)

    def test_docset_name_in_ref_is_case_insensitive(self):
        self.add_py()
        r = self.cli("show", "PY:a#asyncio.sleep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Block for a while.", r.stdout)

    def test_unknown_page_exit_5(self):
        self.add_py()
        r = self.cli("show", "py:nope")
        self.assertEqual(r.returncode, 5)
        self.assertIn("nope", r.stderr)
        r = self.cli("show", "zzz:a")
        self.assertEqual(r.returncode, 5)
        self.assertIn("zzz", r.stderr)

    def test_unknown_anchor_shows_page_start(self):
        self.add_py()
        r = self.cli("show", "py:a#x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning: no #x on a", r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "# Asyncio")
        self.assertIn("Block for a while.", r.stdout)
        self.assertNotIn("anchor not found", r.stdout)

    def test_bad_ref_exit_2(self):
        self.add_py()
        for bad in ("garbage", ":a", "py:"):
            with self.subTest(ref=bad):
                r = self.cli("show", bad)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("bad reference", r.stderr)
                self.assertIn("<docset>:<path>[#anchor]", r.stderr)

    def test_max_lines_below_one_rejected(self):
        self.add_py()
        for cmd in (("search", "sleep"), ("show", "py:a")):
            for bad in ("0", "-3", "x"):
                with self.subTest(cmd=cmd[0], bad=bad):
                    r = self.cli(*cmd, "--max-lines", bad)
                    self.assertEqual(r.returncode, 2, r.stderr)

    def test_links_become_refs_for_existing_pages_only(self):
        self.add("d", [("a", "Guide", "dir/a"), ("b", "Guide", "dir/b")],
                 {"dir/a": ("<p><a href='b#sec'>rel</a> <a href='../top#x'>up</a> "
                            "<a href='/dir/b'>root</a> <a href='./b'>dot</a> "
                            "<a href='missing'>gone</a> <a href='#here'>self</a> "
                            "<a href='https://e.com/x'>web</a></p>"),
                  "dir/b": "<p>B</p>", "top": "<p>T</p>"})
        r = self.cli("show", "d:dir/a")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("rel [d:dir/b#sec]", out)
        self.assertIn("up [d:top#x]", out)
        self.assertIn("root [d:dir/b]", out)
        self.assertIn("dot [d:dir/b]", out)
        self.assertIn("gone self web", out)  # no suffix for these

    def test_no_notes_flag_accepted(self):
        self.add_py()
        r = self.cli("show", "py:guide", "--no-notes")
        self.assertEqual(r.returncode, 0, r.stderr)


class ShowGrepTests(unittest.TestCase):
    PAGE = ("<html><body><h2 id='params'>Parameters</h2><p>Options for read_csv.</p>"
            "<table><tr><th>Name</th><th>Type</th><th>Default</th></tr>"
            "<tr><td>header</td><td>BOOL</td><td>false</td></tr>"
            "<tr><td>sep</td><td>VARCHAR</td><td>,</td></tr>"
            "<tr><td>skip</td><td>BIGINT</td><td>0</td></tr>"
            "<tr><td>quote</td><td>VARCHAR</td><td>\"</td></tr></table>"
            "<p>Use SKIP to ignore leading lines.</p></body></html>")
    DL_PAGE = (
        "<html><body><h2 id='f'>read_csv</h2>"
        "<dl><dt id='sig'>read_csv(path, on_bad_lines='error', low_memory=True)</dt>"
        "<dd><p>Read a file.</p><dl>"
        "<dt><strong>on_bad_lines</strong> {'error', 'warn'}, default 'error'</dt>"
        "<dd><p>What to do with a bad line. Allowed values are:</p>"
        "<ul><li>'error', raise.</li><li>'warn', warn and skip.</li></ul>"
        "<p>Changed in version 2.2.</p></dd>"
        "<dt><strong>low_memory</strong> bool, default True</dt>"
        "<dd><p>Process the file in chunks.</p></dd>"
        "<dt><strong>long_one</strong> str</dt><dd>"
        + "".join("<p>long line %d</p>" % i for i in range(60))
        + "</dd></dl></dd></dl></body></html>")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        make_devdocs(self.cache, "duck", name="Duck", release="1",
                     entries=[("Parameters", "Section", "p#params")],
                     pages={"p": self.PAGE})
        make_devdocs(self.cache, "pan", name="Pan", release="1",
                     entries=[("read_csv", "Function", "d#f")],
                     pages={"d": self.DL_PAGE})

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def test_grep_keeps_heading_table_header_and_matches(self):
        r = self.cli("show", "duck:p#params", "--grep", "skip", "--no-notes")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("## Parameters"), lines)
        row = next(k for k, l in enumerate(lines) if "skip" in l and "BIGINT" in l)
        self.assertIn("Name", lines[row - 2])  # the table's header row, then "..."
        self.assertEqual(lines[row - 1], "...")
        self.assertIn("Use SKIP to ignore leading lines.", r.stdout)
        for gone in ("header", "VARCHAR", "Options for read_csv"):
            self.assertNotIn(gone, r.stdout)
        self.assertEqual(lines[-1], "(all 2 lines containing 'skip' are shown; "
                                    "the section has 8 lines)")

    def test_grep_repeatable_and_no_match(self):
        r = self.cli("show", "duck:p#params", "--grep", "skip", "--grep", "quote")
        self.assertIn("BIGINT", r.stdout)
        self.assertIn("quote", r.stdout)
        r = self.cli("show", "duck:p#params", "--grep", "zzz")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("no lines match"), r.stdout)
        self.assertIn("drop --grep", r.stdout)

    def test_grep_on_a_definition_term_shows_its_definition(self):
        r = self.cli("show", "pan:d#f", "--grep", "on_bad_lines")
        self.assertEqual(r.returncode, 0, r.stderr)
        for kept in ("What to do with a bad line. Allowed values are:",
                     "- 'error', raise.", "- 'warn', warn and skip.",
                     "Changed in version 2.2."):
            self.assertIn(kept, r.stdout)
        self.assertNotIn("Process the file in chunks", r.stdout)
        self.assertNotIn("Read a file.", r.stdout)
        self.assertNotIn("long line", r.stdout)
        self.assertIn("read_csv(path, on_bad_lines='error'", r.stdout)
        self.assertIn("(all 2 lines containing 'on_bad_lines' are shown", r.stdout)
        self.assertIn("definition", r.stdout.splitlines()[-1])

    def test_grep_long_definition_is_not_added(self):
        r = self.cli("show", "pan:d#f", "--grep", "long_one")
        self.assertIn("long_one", r.stdout)
        self.assertNotIn("long line", r.stdout)

    def test_grep_match_inside_a_definition_adds_nothing(self):
        r = self.cli("show", "pan:d#f", "--grep", "warn and skip")
        self.assertIn("- 'warn', warn and skip.", r.stdout)
        self.assertNotIn("Changed in version", r.stdout)


class AnchorlessShowTests(unittest.TestCase):
    def test_show_starts_at_heading_named_like_entry(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = os.path.realpath(tmp.name)
        cache = os.path.join(root, "cache")
        page = ("<html><body><h1>Date Functions</h1><p>intro</p>"
                "<h4 id='date_subpart'>date_sub(part, a, b)</h4><p>signed length</p>"
                "<h4 id='other'>other()</h4><p>nope</p></body></html>")
        make_devdocs(cache, "duck", name="Duck", release="1",
                     entries=[("date_sub", "Function", "d")], pages={"d": page})
        r = run_cli("show", "duck:d", env={"HOME": root, "DOCSHELF_CACHE_DIR": cache,
                                           "DOCSHELF_NOTES_DIR": os.path.join(root, "n")},
                    cwd=root)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "(page: Date Functions)")
        self.assertTrue(lines[1].startswith("#### date_sub(part, a, b)"), r.stdout)
        self.assertIn("signed length", r.stdout)
        self.assertNotIn("intro", r.stdout)
        self.assertNotIn("nope", r.stdout)


class NotesTests(unittest.TestCase):
    PAGE = ("<h2 id='asyncio.gather'>asyncio.gather</h2>"
            "<p>Run awaitables concurrently.</p>")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.notes = os.path.join(self.tmp, "notes")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": self.notes}
        self.cfg = shelf_core.Config(self.cache, self.notes, None, [],
                                     "env", "env")

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def add(self, slug, release="1", entries=None, pages=None, name="Python"):
        make_devdocs(self.cache, slug, name=name, release=release,
                     entries=entries or [
                         ("asyncio.gather", "Function", "a#asyncio.gather"),
                         ("Guide", "Guide", "guide")],
                     pages=pages or {"a": self.PAGE,
                                     "guide": "<h1>Guide</h1><p>Text.</p>"})

    def ds(self, name):
        return shelf_core.pick_docset(shelf_devdocs.installed_docsets(self.cfg),
                                      name)

    def write_notes(self, family, text):
        path = shelf_notes.notes_path(self.cfg, family)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_notes_path(self):
        self.assertEqual(shelf_notes.notes_path(self.cfg, "python"),
                         os.path.join(self.notes, "python.md"))
        for bad in ("", "../x", "a/b", "a\\b", ".hidden", "-x"):
            with self.assertRaises(shelf_core.CLIError) as cm:
                shelf_notes.notes_path(self.cfg, bad)
            self.assertEqual(cm.exception.code, 2)

    def test_notes_path_creates_dir_and_check_ok(self):
        self.add("python")
        r = self.cli("notes", "python", "--path")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), os.path.join(self.notes, "python.md"))
        self.assertTrue(os.path.isdir(self.notes))
        self.write_notes("python", "## General\nok\n")
        r = self.cli("notes", "python", "--check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.startswith("notes file present: "), r.stdout)
        self.assertEqual(r.stdout.splitlines()[-1], "ok")

    def test_notes_check_says_what_each_heading_matched(self):
        self.add("python")
        self.write_notes("python", "## General\ng\n## asyncio.gather\nfn\n"
                         "## Guide (Guide)\nx\n")
        r = self.cli("notes", "python", "--check")
        self.assertEqual(r.returncode, 0, r.stdout)
        lines = r.stdout.splitlines()
        self.assertIn("## General: shown by every show of this docset", lines)
        self.assertIn("## asyncio.gather: shown by show python:a#asyncio.gather",
                      lines)
        self.assertIn("## Guide (Guide): shown by show python:guide", lines)

    def test_notes_file_not_present_messages_parallel(self):
        self.add("python")
        for args in (("notes", "python"), ("notes", "python", "--check")):
            r = self.cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("notes file not present: "),
                            r.stdout)

    def test_notes_output_keeps_headings(self):
        self.add("python")
        self.write_notes("python", "gen\n## asyncio.gather (Function)\nfn\n")
        ds = self.ds("python")
        out = shelf_notes.notes_for(self.cfg, ds, "asyncio.gather", "Function")
        self.assertEqual(out[1:], ["## General", "gen",
                                   "## asyncio.gather (Function)", "fn"])
        self.assertEqual(shelf_notes.general_notes(self.cfg, ds)[1:],
                         ["## General", "gen"])

    def test_parse_notes(self):
        general, sections = shelf_notes.parse_notes(
            "# Title\nintro\n## Asyncio.Gather (Function)\nA\n## other\nB\n"
            "## General\nG2\n")
        self.assertEqual(general, ["intro", "G2"])
        self.assertEqual(sections["asyncio.gather"], [("Function", ["A"])])
        self.assertEqual(sections["other"], [(None, ["B"])])
        self.assertNotIn("general", sections)
        general, _ = shelf_notes.parse_notes("\n\n# Title\nintro\n")
        self.assertEqual(general, ["intro"])
        self.assertEqual(
            shelf_notes.parse_notes("## f (Type)\nx\n")[1]["f"][0][0], "Type")

    def test_notes_heading_without_arguments(self):
        self.add("python", entries=[("asyncio.gather()", "Function", "a")],
                 pages={"a": "<p>x</p>"})
        self.write_notes("python", "## asyncio.gather\nreturn_exceptions\n")
        out = shelf_notes.notes_for(self.cfg, self.ds("python"),
                                    "asyncio.gather()", "Function")
        self.assertIn("return_exceptions", out)
        names = {"asyncio.gather()", "asyncio.sleep()"}
        self.assertEqual(
            shelf_notes.check_notes("## asyncio.gather\nx\n", names), [])
        warns = shelf_notes.check_notes("## asyncio.gathr\nx\n", names)
        self.assertEqual(len(warns), 1)
        self.assertIn("part before '('", warns[0])
        self.assertIn("did you mean 'asyncio.gather", warns[0])

    def test_notes_match_case_and_type(self):
        self.add("python")
        self.write_notes("python", "gen line\n## ASYNCIO.gather (function)\nfn note\n"
                         "## asyncio.gather (Guide)\nguide note\n"
                         "## asyncio.gather\nany note\n## unrelated\nnope\n")
        out = "\n".join(shelf_notes.notes_for(
            self.cfg, self.ds("python"), "Asyncio.Gather", "Function"))
        self.assertIn("--- notes (", out)
        self.assertIn("gen line", out)
        self.assertIn("fn note", out)
        self.assertIn("any note", out)
        self.assertNotIn("guide note", out)
        self.assertNotIn("nope", out)
        self.add("other", name="Other")
        self.assertEqual(shelf_notes.notes_for(
            self.cfg, self.ds("other"), "x", "y"), [])

    def test_notes_shown_with_show(self):
        self.add("python")
        self.write_notes("python", "general tip\n## asyncio.gather\nuse return_exceptions\n")
        r = self.cli("show", "python:a#asyncio.gather")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Run awaitables concurrently.", r.stdout)
        self.assertIn("use return_exceptions", r.stdout)
        self.assertIn("general tip", r.stdout)
        r = self.cli("show", "python:a#asyncio.gather", "--no-notes")
        self.assertNotIn("use return_exceptions", r.stdout)
        self.assertNotIn("general tip", r.stdout)
        r = self.cli("show", "python:guide")  # not a named section: General only
        self.assertIn("general tip", r.stdout)
        self.assertNotIn("use return_exceptions", r.stdout)
        r = self.cli("search", "gather", "-d", "python", "--json")
        self.assertNotIn("general tip", r.stdout)  # notes only with show
        json.loads(r.stdout)

    def test_show_warns_on_size_only(self):
        self.add("python")
        self.write_notes("python", "## asyncio.gather\n" + "x\n" * 250
                         + "## orphan heading\ny\n")
        r = self.cli("show", "python:a#asyncio.gather")
        self.assertEqual(r.returncode, 0)
        self.assertIn("asyncio.gather", r.stderr)
        self.assertNotIn("orphan heading", r.stderr)

    def test_notes_shared_by_family(self):
        self.add("python~3.13", release="3.13")
        self.add("python~3.14", release="3.14")
        path = self.write_notes("python", "## asyncio.gather\nshared note\n")
        for slug in ("python~3.13", "python~3.14"):
            r = self.cli("show", slug + ":a#asyncio.gather")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("shared note", r.stdout)
            self.assertIn(path, r.stdout)

    def test_notes_name_resolves_family_with_two_releases(self):
        self.add("python~3.13", release="3.13")
        self.add("python~3.14", release="3.14",
                 entries=[("asyncio.gather", "Function", "a#asyncio.gather"),
                          ("only314", "Function", "a#only314")],
                 pages={"a": self.PAGE + "<h2 id='only314'>only314</h2>"})
        r = self.cli("notes", "python", "--path")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), os.path.join(self.notes, "python.md"))
        r = self.cli("notes", "PYTHON~3.13", "--path")  # a release name works
        self.assertEqual(r.stdout.strip(), os.path.join(self.notes, "python.md"))
        self.write_notes("python", "## only314\nx\n## asyncio.gather\ny\n")
        r = self.cli("notes", "python", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = next(l for l in r.stdout.splitlines()
                    if l.startswith("## asyncio.gather"))
        self.assertIn("python~3.13:a#asyncio.gather", line)
        self.assertIn("python~3.14:a#asyncio.gather", line)
        self.write_notes("python", "## ghost\nx\n")
        r = self.cli("notes", "python", "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ghost", r.stdout)

    def test_check_limits(self):
        w = shelf_notes.check_notes("## a\n" + "x\n" * 250, {"a"})
        self.assertTrue(any("'a'" in x and "100" in x for x in w), w)
        text = "".join("## s%d\n%s" % (i, "x\n" * 9) for i in range(100))
        names = {"s%d" % i for i in range(100)}
        self.assertEqual(shelf_notes.check_notes(text, names), [])
        self.assertTrue(shelf_notes.check_notes("x\n" * 51, set()))
        big = "".join("## t%d\n%s" % (i, "x\n" * 99) for i in range(21))
        w = shelf_notes.check_notes(big, {"t%d" % i for i in range(21)})
        self.assertTrue(any("2,000" in x or "2000" in x for x in w), w)

    def test_parenthesised_entry_names(self):
        self.add("c", name="C", entries=[("strlen()", "Function", "s#strlen")],
                 pages={"s": '<h2 id="strlen">strlen</h2><p>Length.</p>'})
        self.write_notes("c", "## strlen()\nnul-terminated only\n")
        r = self.cli("show", "c:s#strlen")
        self.assertIn("nul-terminated only", r.stdout)
        self.assertEqual(self.cli("notes", "c", "--check").returncode, 0)

    def test_check_orphans(self):
        w = shelf_notes.check_notes("## real\nx\n## ghost (Type)\ny\n", {"real"})
        self.assertEqual(len(w), 1)
        self.assertIn("ghost", w[0])

    def test_notes_check_cli_and_unknown(self):
        self.add("python")
        self.write_notes("python", "## asyncio.gather\nok\n")
        r = self.cli("notes", "python", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.write_notes("python", "## ghost\nok\n")
        r = self.cli("notes", "python", "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ghost", r.stdout)
        r = self.cli("notes", "Missing", "--check")
        self.assertEqual(r.returncode, 5)

    def test_underscore_family(self):
        self.add("react_native", name="React Native",
                 entries=[("Animated", "Class", "a#asyncio.gather")])
        self.write_notes("react_native", "## Animated\nunderscore note\n")
        r = self.cli("show", "react_native:a#asyncio.gather")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("underscore note", r.stdout)
        r = self.cli("notes", "react_native", "--path")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip().endswith("react_native.md"), r.stdout)

    def test_notes_name_cannot_escape(self):
        self.add("python")
        r = self.cli("notes", "../evil", "--path")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.md")))


class FtsTests(unittest.TestCase):
    PY_PAGE = ("<h1>Asyncio</h1><h2 id='asyncio.gather'>asyncio.gather</h2>"
               "<p>Run awaitables concurrently.</p><pre>await asyncio.gather(a(), b())</pre>"
               "<h2 id='asyncio.sleep'>asyncio.sleep</h2><p>Block for a while.</p>")
    GUIDE = "<h1>Guide</h1><p>Gather things together, gather gather gather.</p>"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        self.add_py()

    def add(self, slug, entries, pages, name=None, **kw):
        return make_devdocs(self.cache, slug, name=name or slug.capitalize(),
                            release="1", entries=entries, pages=pages, **kw)

    def add_py(self, **kw):
        return self.add("py", [("asyncio.gather", "Function", "a#asyncio.gather"),
                               ("asyncio.sleep", "Function", "a#asyncio.sleep"),
                               ("Guide", "Guide", "guide")],
                        {"a": self.PY_PAGE, "guide": self.GUIDE}, **kw)

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def db(self):
        return os.path.join(self.cache, "devdocs", "py", ".docshelf", "fts.sqlite")

    def test_fts_finds_text_in_page(self):
        r = self.cli("fts", "b()", "-d", "py")  # only in <pre>, with FTS syntax
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "py:a#asyncio.gather")
        self.assertIn("gather", r.stdout)
        r = self.cli("fts", "Gather things", "-d", "py", "--json")
        items = json.loads(r.stdout)
        self.assertEqual(items[0]["ref"], "py:guide")
        self.assertEqual(sorted(items[0]), ["docset", "page", "ref", "snippet"])
        self.assertEqual(items[0]["page"], "guide")
        r = self.cli("fts", "zzzznothing", "-d", "py")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "no matches for 'zzzznothing'")

    def test_hit_ref_is_page_anchor_when_no_entry(self):
        self.add("duck", [("Other", "Guide", "p")],
                 {"p": "<h2 id='intro'>Intro</h2><p>quack quack</p>"})
        r = self.cli("fts", "quack", "-d", "duck")
        self.assertEqual(r.stdout.splitlines()[0], "duck:p#intro")
        r = self.cli("show", "duck:p#intro", "--no-notes")
        self.assertIn("quack", r.stdout)

    def test_ranking_prefers_denser_page(self):
        r = self.cli("fts", "gather", "-d", "py", "--json")
        self.assertEqual([h["page"] for h in r.stdout and json.loads(r.stdout)],
                         ["guide", "a"])

    def test_snippet_brackets_match(self):
        r = self.cli("fts", "awaitables", "-d", "py", "--json")
        self.assertIn("[awaitables]", json.loads(r.stdout)[0]["snippet"])

    def test_fts_entry_ref_via_second_id(self):
        page = ("<h2 id='params'>Params</h2><p>skip lines at the start</p>")
        self.add("duck", [("Params", "Guide", "p#params")], {"p": page})
        r = self.cli("fts", "skip", "lines", "-d", "duck")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "duck:p#params")

    def test_entry_anchor_percent_encoded(self):
        self.add("duck", [("Out of Memory", "Guide", "p#Out%20of%20Memory")],
                 {"p": "<h2 id='Out of Memory'>Out of Memory</h2><p>heap exhausted</p>"})
        r = self.cli("fts", "exhausted", "-d", "duck")
        self.assertEqual(r.stdout.splitlines()[0], "duck:p#Out%20of%20Memory")

    def test_unquote_all(self):
        self.assertEqual(shelf_lookup._unquote_all("Guide/Out%2520of%2520Memory"),
                         "Guide/Out of Memory")
        self.assertEqual(shelf_lookup._unquote_all("plain"), "plain")

    def test_snippet_phrases(self):
        self.assertEqual(shelf_lookup._snippet_phrases(
            "...Also see \x02context\x03 \x02variable\x03. - A contextvars.\x02Context\x03 object..."),
            ["also see context variable", "context variable"])
        self.assertEqual(shelf_lookup._snippet_phrases(
            "get([default]) Return a value for the \x02context\x03 \x02variable\x03 for"),
            ["for the context variable for", "context variable for"])
        self.assertEqual(shelf_lookup._snippet_phrases("no match marks"), [])

    def test_fts_cap_keeps_ref_with_snippet(self):
        r = self.cli("fts", "gather", "-d", "py", "--max-lines", "2")
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("py:"))
        self.assertTrue(lines[1].startswith("    "))
        self.assertIn("more hits cut", lines[2])

    def test_max_lines_must_be_positive(self):
        r = self.cli("fts", "gather", "-d", "py", "--max-lines", "0")
        self.assertEqual(r.returncode, 2)

    def test_fts_default_is_five_hits_with_hint(self):
        pages = {"p%02d" % i: "<p>needle %s</p>" % ("x " * i) for i in range(8)}
        self.add("many", [("x%d" % i, "Guide", p) for i, p in enumerate(pages)], pages)
        r = self.cli("fts", "needle", "-d", "many")
        lines = r.stdout.splitlines()
        self.assertEqual(sum(1 for l in lines if l.startswith("many:")), 5, lines)
        self.assertIn("more hits cut", lines[-1])
        self.assertIn("add words", lines[-1])

    def test_fts_first_build_says_so(self):
        r = self.cli("fts", "gather", "-d", "py")
        self.assertEqual(r.stderr.count("building the full-text index for py"), 1)
        self.assertTrue(os.path.isfile(self.db()))
        r = self.cli("fts", "gather", "-d", "py")
        self.assertEqual(r.stderr, "")

    def test_index_text_builds_and_layout(self):
        r = self.cli("index-text", "py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "indexed 2 pages of py")
        self.assertEqual(r.stderr, "")
        con = sqlite3.connect(self.db())
        self.assertEqual(con.execute("SELECT COUNT(*) FROM pages").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM page_entries").fetchone()[0], 3)
        refs = {x for (x,) in con.execute("SELECT ref FROM page_entries")}
        self.assertIn("py:a#asyncio.sleep", refs)
        keys = {k for k, _ in con.execute("SELECT key, value FROM meta")}
        self.assertEqual(keys, {"docset_version", "built_at"})
        con.close()
        r = self.cli("fts", "gather", "-d", "py")  # already built: silent
        self.assertEqual(r.stderr, "")
        r = self.cli("index-text", "nope")
        self.assertEqual(r.returncode, 5)

    def test_fts_rebuilds_when_docset_rewritten(self):
        self.cli("fts", "gather", "-d", "py")
        self.add("py", [("asyncio.gather", "Function", "a#asyncio.gather"),
                        ("Guide", "Guide", "guide")],
                 {"a": self.PY_PAGE, "guide": self.GUIDE + "<p>newword</p>"},
                 mtime=1800000000)  # new content, size and mtime
        r = self.cli("fts", "newword", "-d", "py")
        self.assertIn("rebuilt index for py", r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "py:guide")

    def test_stale_index_rebuilt_in_place(self):
        self.cli("fts", "gather", "-d", "py")
        folder = os.path.join(self.cache, "devdocs", "py")
        with open(os.path.join(folder, "db.json"), encoding="utf-8") as f:
            pages = json.load(f)
        pages["guide"] += "<p>newword</p>"
        with open(os.path.join(folder, "db.json"), "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        r = self.cli("fts", "newword", "-d", "py")
        self.assertIn("rebuilt index for py", r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "py:guide")
        r = self.cli("fts", "newword", "-d", "py")
        self.assertEqual(r.stderr, "")

    def test_fts_unavailable(self):
        import contextlib
        import io
        from unittest import mock
        for argv in (["fts", "x", "-d", "py"], ["index-text", "py"]):
            err = io.StringIO()
            with mock.patch.object(shelf_lookup, "fts_available", return_value=False), \
                    mock.patch.dict(os.environ, self.env), \
                    contextlib.redirect_stderr(err):
                code = shelf_cli.main(argv)
            self.assertEqual(code, 2)
            self.assertIn("FTS5", err.getvalue())

    def test_fts_scope_error(self):
        big = [("e%d" % i, "Function", "p") for i in range(500)]
        for i in range(5):
            self.add("b%d" % i, big, {"p": "<p>x</p>"})
        r = self.cli("fts", "x")
        self.assertEqual(r.returncode, 4)

    def test_fts_fetches_enough_hits_for_line_cap(self):
        import contextlib
        import io
        from unittest import mock
        seen = []

        def fake(cfg, docs, query, limit):
            seen.append(limit)
            return []
        for argv, want in ((["--max-lines", "10"], 6),
                           (["--max-lines", "10", "--json"], 10)):
            with mock.patch.object(shelf_lookup, "fts_search", fake), \
                    mock.patch.dict(os.environ, self.env), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                shelf_cli.main(["fts", "word", "-d", "py"] + argv)
            self.assertEqual(seen[-1], want)


class FakeNet:
    """Replaces shelf_devdocs.fetch(url, dest=None); records the calls."""

    def __init__(self, test, pages=None):
        self.pages = dict(pages or {})
        self.fetched = []
        p = mock.patch.object(shelf_devdocs, "fetch", self.fetch)
        p.start()
        test.addCleanup(p.stop)

    def fetch(self, url, dest=None):
        self.fetched.append(url)
        v = self.pages.get(url)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise shelf_devdocs.NetError(url, "HTTP 404")
        data = v if isinstance(v, bytes) else v.encode("utf-8")
        if dest is None:
            return data
        with open(dest, "wb") as f:
            f.write(data)
        return b""


def remote_docset(slug, entries, pages):
    """The two documents documents.devdocs.io serves for a slug."""
    base = "%s/%s/" % (shelf_devdocs.DOCUMENTS_BASE, slug)
    index = {"entries": [{"name": n, "type": t, "path": p} for n, t, p in entries],
             "types": []}
    return {base + "index.json": json.dumps(index),
            base + "db.json": json.dumps(pages, ensure_ascii=False)}


def row(name, slug, release, mtime=1700000000, version="", alias=None,
        db_size=2_500_000):
    return {"name": name, "slug": slug, "type": slug.split("~")[0],
            "version": version, "release": release, "mtime": mtime,
            "db_size": db_size, "attribution": "", "alias": alias, "links": {}}


class NetworkTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.notes = os.path.join(self.tmp, "notes")
        self.root = os.path.join(self.cache, "devdocs")
        os.makedirs(self.root)
        env = mock.patch.dict(os.environ, {"DOCSHELF_CACHE_DIR": self.cache,
                                           "DOCSHELF_NOTES_DIR": self.notes})
        env.start()
        self.addCleanup(env.stop)
        self.pages = {"intro": "<h1>Intro</h1>", "api": "<h1>API</h1>"}
        self.entries = [("Intro", "Guide", "intro"), ("api()", "API", "api#x")]
        self.rows = [row("Python", "python~3.15", "3.15.0", version="3.15", alias="py"),
                     row("Python", "python~3.14", "3.14.8", version="3.14"),
                     row("Node.js", "node", "26.3.1"),
                     row("Node.js", "node~24_lts", "24.1.0", version="24 LTS")]
        self.net = FakeNet(self, self.docs_pages(self.rows))

    def docs_pages(self, rows):
        pages = {shelf_devdocs.MANIFEST_URL: json.dumps(rows)}
        for r in rows:
            pages.update(remote_docset(r["slug"], self.entries, self.pages))
        return pages

    def write_manifest(self, rows, age=0):
        path = os.path.join(self.root, "docs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        if age:
            t = os.path.getmtime(path) - age
            os.utime(path, (t, t))

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def meta(self, slug):
        with open(os.path.join(self.root, slug, "meta.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_install_family_newest(self):
        code, out, err = self.main("install", "python")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "installed python~3.15 (Python 3.15.0, 2 entries)\n")
        m = self.meta("python~3.15")
        self.assertEqual((m["version"], m["release"], m["alias"], m["mtime"]),
                         ("3.15", "3.15.0", "py", 1700000000))
        self.assertTrue(m["installedAt"].endswith("Z"))
        self.assertTrue(os.path.isfile(
            os.path.join(self.root, "python~3.15", ".docshelf", "pages.json")))
        self.assertEqual(self.main("install", "node")[1].split()[1], "node")

    def test_install_alias(self):
        code, out, _ = self.main("install", "py")
        self.assertEqual(out.split()[:2], ["installed", "python~3.15"])
        self.assertEqual(self.main("install", "PYTHON~3.14")[1].split()[1],
                         "python~3.14")
        self.assertEqual(self.main("install", "node~24_lts")[1].split()[1],
                         "node~24_lts")
        self.assertIn(" node~24_lts (", self.main("install", "Node.js 24 LTS")[1])

    def test_unknown_name_lists_close_slugs(self):
        code, out, err = self.main("install", "pyth")
        self.assertEqual(code, 5)
        self.assertIn("python~3.15", err)
        self.assertEqual(self.main("install", "zzz")[0], 5)

    def test_install_up_to_date(self):
        self.main("install", "python")
        before = len(self.net.fetched)
        code, out, _ = self.main("install", "python")
        self.assertEqual(out, "up to date python~3.15 (Python 3.15.0, 2 entries)\n")
        self.assertEqual(len(self.net.fetched), before)  # manifest cached too

    def test_update_newer_mtime(self):
        self.main("install", "python~3.14")
        newer = [dict(r, mtime=1800000000, release="3.14.9")
                 if r["slug"] == "python~3.14" else r for r in self.rows]
        self.net.pages.update(self.docs_pages(newer))
        self.write_manifest(newer)
        code, out, err = self.main("update")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "updated python~3.14 (Python 3.14.9, 2 entries)\n")
        self.assertEqual(self.meta("python~3.14")["mtime"], 1800000000)
        self.assertEqual(self.main("update", "python")[1].split()[0], "up")

    def test_update_gone_from_manifest_warns(self):
        self.main("install", "python~3.14", "node")
        rest = [r for r in self.rows if r["slug"] != "python~3.14"]
        self.write_manifest(rest)
        self.net.pages[shelf_devdocs.MANIFEST_URL] = json.dumps(rest)
        code, out, err = self.main("update")
        self.assertEqual(code, 0)
        self.assertIn("python~3.14", err)
        self.assertTrue(out.startswith("up to date node ("), out)

    def test_install_failure_leaves_nothing(self):
        url = "%s/python~3.15/db.json" % shelf_devdocs.DOCUMENTS_BASE
        self.net.pages[url] = shelf_devdocs.NetError(url, "connection reset")
        code, _, err = self.main("install", "python")
        self.assertEqual(code, 7)
        self.assertIn("documents.devdocs.io", err)
        folder = os.path.join(self.root, "python~3.15")
        self.assertFalse(os.path.exists(os.path.join(folder, "meta.json")))
        leftovers = [f for _, _, fs in os.walk(folder) for f in fs]
        self.assertEqual(leftovers, [])

    def test_failed_update_keeps_old_docset(self):
        self.main("install", "python~3.14")
        newer = [dict(r, mtime=1800000000) for r in self.rows]
        self.write_manifest(newer)
        self.net.pages[shelf_devdocs.MANIFEST_URL] = json.dumps(newer)
        url = "%s/python~3.14/db.json" % shelf_devdocs.DOCUMENTS_BASE
        self.net.pages[url] = shelf_devdocs.NetError(url, "boom")
        self.assertEqual(self.main("update")[0], 7)
        self.assertEqual(self.meta("python~3.14")["mtime"], 1700000000)
        self.assertEqual(
            [f for f in os.listdir(os.path.join(self.root, "python~3.14"))
             if f.endswith(".tmp")], [])

    def test_bad_manifest_body_is_network_error(self):
        self.net.pages[shelf_devdocs.MANIFEST_URL] = "<html>captive portal"
        code, _, err = self.main("sources", "python")
        self.assertEqual(code, 7)

    def test_manifest_stale_fallback_note(self):
        self.write_manifest(self.rows, age=3 * 86400)
        self.net.pages[shelf_devdocs.MANIFEST_URL] = shelf_devdocs.NetError(
            shelf_devdocs.MANIFEST_URL, "timed out")
        code, out, err = self.main("sources", "python")
        self.assertEqual(code, 0)
        self.assertIn("python~3.15", out)
        self.assertRegex(err, r"note: using the cached DevDocs list from "
                              r"\d{4}-\d\d-\d\d \(could not reach devdocs\.io\)")

    def test_stale_manifest_refetched(self):
        self.write_manifest([], age=3 * 86400)
        code, out, _ = self.main("sources", "node")
        self.assertIn("node~24_lts", out)
        self.assertEqual(self.net.fetched, [shelf_devdocs.MANIFEST_URL])

    def test_no_manifest_exit_7(self):
        self.net.pages[shelf_devdocs.MANIFEST_URL] = shelf_devdocs.NetError(
            shelf_devdocs.MANIFEST_URL, "blocked")
        code, out, err = self.main("sources", "python")
        self.assertEqual(code, 7)
        self.assertIn("devdocs.io", err)
        self.assertIn("documents.devdocs.io", err)
        self.assertIn("assets/allowlist.txt", err)

    def test_bad_slug_exit_2(self):
        self.write_manifest([row("Evil", "../x", "1")])
        code, _, err = self.main("install", "../x")
        self.assertEqual(code, 2)
        self.assertIn("../x", err)
        self.assertFalse(os.path.exists(os.path.join(self.cache, "x")))

    def test_sources_marks_installed(self):
        self.main("install", "python~3.14")
        code, out, _ = self.main("sources", "python")
        lines = out.splitlines()
        self.assertEqual(lines, [
            "python~3.14  Python  3.14.8  2.5 MB  (installed)",
            "python~3.15  Python  3.15.0  2.5 MB"])
        out = self.main("sources", "node", "lts")[1]
        self.assertEqual(out.splitlines(),
                         ["node~24_lts  Node.js  24.1.0  2.5 MB"])

    def test_sources_caps_rows(self):
        self.write_manifest([row("X%d" % i, "x%d" % i, "1") for i in range(40)])
        self.assertEqual(len(self.main("sources", "x")[1].splitlines()), 30)

    def test_remove_keeps_notes(self):
        self.main("install", "python~3.14")
        os.makedirs(self.notes)
        note = os.path.join(self.notes, "python.md")
        with open(note, "w", encoding="utf-8") as f:
            f.write("# keep me\n")
        code, out, _ = self.main("remove", "python")
        self.assertEqual(code, 0)
        self.assertIn("python~3.14", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "python~3.14")))
        self.assertTrue(os.path.isfile(note))
        self.assertEqual(self.main("remove", "python")[0], 5)


TOP_HELP_EXPECTED = """\
docshelf 0.1.0: look up DevDocs documentation offline (stdlib only).
This is the command reference; `<command> --help` adds only the options
listed at the end. REF = <docset>:<path>[#anchor], as search and fts print
them; <docset> is the name `list` prints.

Look up (usual order):
  search QUERY... [-d NAME]      entries whose names contain all the words;
                                 prints one REF per entry, best first
  show REF                       that entry's section (max 150 lines) plus
                                 your notes for it
  show REF --grep TEXT           only lines containing TEXT, with their
                                 heading, table header row, and a matching
                                 term's definition (repeatable; plain text,
                                 not a pattern, case-insensitive)
  fts QUERY... [-d NAME]         words inside pages, 5 best hits with REFs;
                                 include the function name: fts read_csv skip

Notes (format: references/notes.md in the skill folder):
  notes DOCSET --path            the notes file to edit
  notes DOCSET --check           after editing: which REFs show each section,
                                 then "ok"

Get and manage docsets (references/getting-docsets.md):
  list                           installed docsets and their versions
  sources QUERY...               docsets DevDocs offers, with sizes
  install NAME...                download one (NAME without a version = the
                                 newest); update [NAME...]; remove NAME
  where                          cache, notes folder and project file
  index-text DOCSET              build the fts index now

Only if you need these, see `<command> --help`:
  search     --type --all --max-lines --json
  show       --full --max-lines --no-notes
  fts        --all --max-lines --json
  sources    --refresh
Global: --version, --mcp (run as a stdio MCP server; references/mcp.md).
Exit codes: 0 ok; 1 notes --check found problems; 2 usage error, ambiguous
  name or no FTS5; 4 search scope too wide (use -d, a project list or --all)
  or unknown -d name; 5 not found (docset, page or entry); 7 network
  (DevDocs could not be reached)
"""


class HelpTests(unittest.TestCase):
    def test_top_help_text(self):
        r = run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, TOP_HELP_EXPECTED)

    def test_every_command_in_help(self):
        text = shelf_cli.top_help()
        for c in shelf_cli.COMMANDS:
            self.assertIn(c.name, text)

    def test_subcommand_help_is_argparse(self):
        r = run_cli("search", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--max-lines", r.stdout)

    def test_skill_md_mentions_no_dash_docset(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Credits", text)
        self.assertIn("https://devdocs.io", text)


    def test_no_dash_docset_text_in_any_skill_file(self):
        for dirpath, dirs, files in os.walk(SKILL):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                for bad in ("dash-docset", "docset.py", ".dash-docset"):
                    self.assertNotIn(bad, text, path)


class McpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = clean_env()
        self.env.update({"HOME": self.tmp, "USERPROFILE": self.tmp,
                         "DOCSHELF_CACHE_DIR": self.cache,
                         "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")})
        make_devdocs(self.cache, "alpha", name="Alpha", release="1",
                     entries=[("frobnicate(x)", "Function", "api#frob")],
                     pages={"api": "<h2 id=\"frob\">frobnicate</h2><p>Frobs x.</p>"})
        self.proc = subprocess.Popen(
            [sys.executable, SCRIPT, "--mcp"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=self.env, cwd=self.tmp)
        self.addCleanup(self.stop)
        self.next_id = 0

    def stop(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()

    def send_raw(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def rpc(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        reply = self.send_raw(json.dumps(msg))
        self.assertEqual(reply["id"], self.next_id)
        return reply

    def call(self, name, arguments):
        return self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]

    def test_initialize_and_list(self):
        r = self.rpc("initialize", {"protocolVersion": "2024-11-05",
                                    "capabilities": {}})["result"]
        self.assertEqual(r["protocolVersion"], "2024-11-05")
        self.assertEqual(r["serverInfo"],
                         {"name": "docshelf", "version": shelf_core.VERSION})
        self.assertEqual(r["capabilities"], {"tools": {}})
        r = self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        tools = self.rpc("tools/list")["result"]["tools"]
        by_name = {t["name"]: t for t in tools}
        self.assertEqual(sorted(by_name), ["fts", "install", "list", "notes",
                                           "remove", "search", "show", "sources"])
        q = by_name["search"]["inputSchema"]
        self.assertEqual(q["properties"]["query"]["type"], "array")
        self.assertEqual(q["properties"]["query"]["items"], {"type": "string"})
        self.assertIn("query", q["required"])
        self.assertEqual(q["properties"]["max_lines"]["type"], "integer")
        self.assertEqual(q["properties"]["all"]["type"], "boolean")
        self.assertEqual(q["properties"]["docsets"]["type"], "array")
        self.assertEqual(sorted(by_name["notes"]["inputSchema"]["properties"]),
                         ["check", "docset"])

    def test_search_matches_cli(self):
        r = self.call("search", {"query": ["frobnicate"], "docsets": ["alpha"]})
        self.assertFalse(r["isError"], r)
        cli = run_cli("search", "frobnicate", "-d", "alpha", env=self.env,
                      cwd=self.tmp)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(r["content"][0]["text"], cli.stdout)
        shown = self.call("show", {"ref": "alpha:api#frob"})
        self.assertFalse(shown["isError"])
        self.assertIn("Frobs x.", shown["content"][0]["text"])

    def test_error_is_result(self):
        r = self.call("show", {"ref": "nosuch:page"})
        self.assertTrue(r["isError"])
        self.assertTrue(r["content"][0]["text"])
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_install_error_hint_replaces_file_pointer(self):
        r = self.call("show", {"ref": "nosuch:page"})
        self.assertNotIn("references/", r["content"][0]["text"])

    def test_garbage_line(self):
        reply = self.send_raw("this is not json")
        self.assertEqual(reply["error"]["code"], -32700)
        self.assertIsNone(reply["id"])
        self.assertEqual(self.rpc("ping")["result"], {})
        self.assertEqual(self.rpc("no/such")["error"]["code"], -32601)

    def test_unknown_tool(self):
        self.assertTrue(self.call("where", {})["isError"])
        self.assertTrue(self.call("nope", {})["isError"])

    def test_missing_required_arg(self):
        r = self.call("search", {})
        self.assertTrue(r["isError"])
        self.assertIn("query", r["content"][0]["text"])

    def test_stderr_appended_and_internal_error(self):
        import shelf_mcp
        def noisy(cfg, args):
            print("out line")
            print("warning: careful", file=sys.stderr)
            return 0
        def boom(cfg, args):
            raise RuntimeError("kaput")
        cmds = [shelf_cli.Command("noisy", "x", noisy, []),
                shelf_cli.Command("boom", "x", boom, [])]
        inp = io.StringIO("".join(json.dumps(
            {"jsonrpc": "2.0", "id": i, "method": "tools/call",
             "params": {"name": n, "arguments": {}}}) + "\n"
            for i, n in ((1, "noisy"), (2, "boom"), (3, "noisy"))))
        out = io.StringIO()
        with mock.patch.object(shelf_cli, "COMMANDS", cmds):
            self.assertEqual(shelf_mcp.serve(inp, out), 0)
        replies = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual(replies[0]["result"]["content"][0]["text"],
                         "out line\nwarning: careful\n")
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertEqual(replies[1]["result"]["content"][0]["text"],
                         "internal error: RuntimeError: kaput")
        self.assertFalse(replies[2]["result"]["isError"])

    def test_notes_tool(self):
        r = self.call("notes", {"docset": "alpha"})
        self.assertFalse(r["isError"], r)
        self.assertIn("notes file not present", r["content"][0]["text"])
        os.makedirs(os.path.join(self.tmp, "notes"))
        with open(os.path.join(self.tmp, "notes", "alpha.md"), "w",
                  encoding="utf-8") as f:
            f.write("## frobnicate\nUse it twice.\n")
        r = self.call("notes", {"docset": "alpha"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(r["content"][0]["text"], "## frobnicate\nUse it twice.\n")
        r = self.call("notes", {"docset": "alpha", "check": True})
        self.assertFalse(r["isError"], r)
        self.assertIn("ok", r["content"][0]["text"])

    def test_namespace_has_every_parser_dest(self):
        import shelf_mcp
        for c in shelf_cli.COMMANDS:
            if not c.mcp:
                continue
            args = {}
            for p in shelf_mcp._tool_params(c):
                if shelf_mcp._positional(p) and p.nargs != "*":
                    args[shelf_mcp._prop_name(p)] = (
                        ["x"] if p.nargs == "+" else "x")
            ns = shelf_mcp._build_namespace(c, args)
            sub = shelf_cli.build_parser()._subparsers._group_actions[0] \
                .choices[c.name]
            for a in sub._actions:
                if a.dest != "help":
                    self.assertTrue(hasattr(ns, a.dest), (c.name, a.dest))

    def test_invalid_utf8_line_does_not_kill_server(self):
        ping = lambda i: json.dumps(
            {"jsonrpc": "2.0", "id": i, "method": "ping"}).encode() + b"\n"
        r = subprocess.run([sys.executable, SCRIPT, "--mcp"],
                           input=ping(1) + b"\xff\xfe\n" + ping(2),
                           capture_output=True, env=self.env, cwd=self.tmp)
        replies = [json.loads(l) for l in r.stdout.decode().splitlines()]
        self.assertEqual(len(replies), 3, r.stderr)
        self.assertEqual(replies[0]["id"], 1)
        self.assertEqual(replies[1]["error"]["code"], -32700)
        self.assertIsNone(replies[1]["id"])
        self.assertEqual(replies[2]["id"], 2)

    def test_mcp_doc_linked_and_clean(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            self.assertIn("references/mcp.md", f.read())
        with open(os.path.join(SKILL, "references", "mcp.md"),
                  encoding="utf-8") as f:
            text = f.read()
        for needle in ("claude mcp add docshelf", "mcpServers",
                       "[mcp_servers.docshelf]", '"type": "local"'):
            self.assertIn(needle, text)


class FinalReviewTests(unittest.TestCase):
    """Fixes from the final whole-branch review (I1-I9, M1, M2)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.notes = os.path.join(self.tmp, "notes")
        self.root = os.path.join(self.cache, "devdocs")
        env = mock.patch.dict(os.environ, {"DOCSHELF_CACHE_DIR": self.cache,
                                           "DOCSHELF_NOTES_DIR": self.notes})
        env.start()
        self.addCleanup(env.stop)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def cfg(self):
        return shelf_core.load_config(self.tmp, dict(os.environ))

    def make(self, slug="py", **kw):
        kw.setdefault("name", "Py")
        kw.setdefault("release", "1")
        kw.setdefault("entries", [("Guide", "Guide", "guide")])
        kw.setdefault("pages", {"guide": "<p>gather</p>"})
        return make_devdocs(self.cache, slug, **kw)

    def net(self, rows, pages=None, entries=None):
        entries = entries or [("Intro", "Guide", "intro")]
        data = {shelf_devdocs.MANIFEST_URL: json.dumps(rows)}
        for r in rows:
            data.update(remote_docset(r["slug"], entries,
                                      pages or {"intro": "<h1>Intro</h1>"}))
        return FakeNet(self, data)

    def write_file(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    # I1
    def test_fts_unwritable_data_dir_exits_2(self):
        folder = self.make()
        self.write_file(os.path.join(folder, ".docshelf"), "a file")
        code, _, err = self.main("fts", "gather", "-d", "py")
        self.assertEqual(code, 2, err)
        self.assertIn("DOCSHELF_CACHE_DIR", err)
        self.assertNotIn("Traceback", err)

    def test_notes_path_dir_is_file_exits_2(self):
        self.make()
        self.write_file(self.notes, "a file")
        code, _, err = self.main("notes", "py", "--path")
        self.assertEqual(code, 2, err)
        self.assertIn("DOCSHELF_NOTES_DIR", err)
        self.assertNotIn("Traceback", err)

    def test_sources_uncreatable_cache_exits_2(self):
        self.write_file(self.cache, "a file")
        self.net([row("Python", "python~3.15", "3.15.0")])
        code, _, err = self.main("sources", "python")
        self.assertEqual(code, 2, err)
        self.assertIn("DOCSHELF_CACHE_DIR", err)
        self.assertNotIn("Traceback", err)

    def test_install_uncreatable_folder_exits_2(self):
        rows = [row("Python", "python~3.15", "3.15.0")]
        self.net(rows)
        self.write_file(os.path.join(self.root, "docs.json"), json.dumps(rows))
        self.write_file(os.path.join(self.root, "python~3.15"), "a file")
        code, _, err = self.main("install", "python")
        self.assertEqual(code, 2, err)
        self.assertIn("DOCSHELF_CACHE_DIR", err)
        self.assertNotIn("Traceback", err)

    def test_last_resort_handler(self):
        for exc, line in (
                (ValueError("boom"), "error: ValueError: boom\n"),
                (sqlite3.OperationalError("disk I/O error"),
                 "error: OperationalError: disk I/O error\n"),
                (PermissionError("denied"), "error: PermissionError: denied\n")):
            with mock.patch.object(shelf_devdocs, "installed_docsets",
                                   side_effect=exc):
                code, out, err = self.main("list")
            self.assertEqual((code, out, err), (2, "", line))

    # I2
    def test_download_write_error_is_local_not_network(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"data"

        dest = os.path.join(self.tmp, "no-such-dir", "db.json.tmp")
        with mock.patch.object(shelf_devdocs.urllib.request, "urlopen",
                               return_value=Resp()):
            with self.assertRaises(CLIError) as cm:
                shelf_devdocs.fetch(shelf_devdocs.DOCUMENTS_BASE + "/x/db.json",
                                    dest)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("db.json.tmp", str(cm.exception))
        self.assertNotIn("allowlist", str(cm.exception))
        self.assertNotIsInstance(cm.exception, shelf_devdocs.NetError)

    # I3
    def test_concurrent_fts_builds(self):
        self.make()
        a = shelf_devdocs.installed_docsets(self.cfg())[0]
        b = shelf_devdocs.installed_docsets(self.cfg())[0]
        started, proceed = threading.Event(), threading.Event()
        real = a.page_html

        def slow(page):
            started.set()
            proceed.wait(30)
            return real(page)

        a.page_html = slow
        errors = []

        def run_a():
            try:
                shelf_lookup.build_fts(self.cfg(), a)
            except BaseException as e:  # reported below
                errors.append(e)

        t = threading.Thread(target=run_a)
        t.start()
        self.assertTrue(started.wait(30))
        shelf_lookup.build_fts(self.cfg(), b)  # finishes while a is mid-build
        proceed.set()
        t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(shelf_lookup._stored_stamp(shelf_lookup.fts_path(b)),
                         shelf_lookup.fts_stamp(b))
        left = [f for f in os.listdir(b.data_dir()) if f.endswith(".tmp")]
        self.assertEqual(left, [])

    # I4
    def test_update_refreshes_cached_manifest(self):
        old = [row("Python", "python~3.14", "3.14.8", version="3.14")]
        self.net(old)
        self.assertEqual(self.main("install", "python~3.14")[0], 0)
        new = [dict(old[0], mtime=1800000000, release="3.14.9")]
        self.net(new)  # the cached docs.json is fresh but old
        code, out, err = self.main("update")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("updated python~3.14 (Python 3.14.9"), out)

    def test_update_duplicate_slug_uses_first_row(self):
        first = row("Bun", "bun", "1.4.0", mtime=1700000000)
        second = row("Bun", "bun", "1.3.12", mtime=1800000000)
        self.net([first, second])
        self.assertEqual(self.main("install", "bun")[0], 0)
        code, out, _ = self.main("update")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("up to date bun ("), out)

    # I5
    def test_corrupt_cached_manifest_and_failed_fetch_exits_7(self):
        path = os.path.join(self.root, "docs.json")
        self.write_file(path, "{not json")
        old = os.path.getmtime(path) - 3 * 86400
        os.utime(path, (old, old))
        url = shelf_devdocs.MANIFEST_URL
        with mock.patch.object(shelf_devdocs, "fetch",
                               side_effect=shelf_devdocs.NetError(url, "timed out")):
            code, _, err = self.main("sources", "python")
        self.assertEqual(code, 7, err)
        self.assertIn("devdocs.io", err)
        self.assertNotIn("Traceback", err)

    # I6
    def test_truncated_db_json_raises_value_error(self):
        for text in ('{"a"', '{"a":', '{"a": ', '{"a": "x"', '{"a": "x",',
                     '{"a": "x"} junk', '{'):
            path = os.path.join(self.tmp, "db.json")
            self.write_file(path, text)
            with self.assertRaises(ValueError, msg=text):
                shelf_devdocs.build_page_index(path)
        self.write_file(path, ' {"a": "x" , "b": "y"} \n')
        self.assertEqual(sorted(shelf_devdocs.build_page_index(path)), ["a", "b"])
        self.write_file(path, "{}")
        self.assertEqual(shelf_devdocs.build_page_index(path), {})

    def test_show_on_truncated_db_json_exits_cleanly(self):
        folder = self.make()
        self.write_file(os.path.join(folder, "db.json"), '{"guide":')
        code, _, err = self.main("show", "py:guide")
        self.assertEqual(code, 5, err)
        self.assertIn("reinstall", err)
        self.assertNotIn("Traceback", err)

    # I7
    def test_index_json_not_an_object_is_skipped_and_removable(self):
        self.make("good")
        folder = self.make("bad")
        self.write_file(os.path.join(folder, "index.json"), "[]")
        code, out, err = self.main("list")
        self.assertEqual(code, 0, err)
        self.assertIn("skipping", err)
        self.assertIn("good", out)
        self.assertNotIn("bad", out)
        code, out, err = self.main("remove", "bad")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(folder))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "good")))
        self.assertEqual(self.main("remove", "bad")[0], 5)

    def test_index_json_entries_not_a_list_is_skipped(self):
        folder = self.make("bad")
        self.write_file(os.path.join(folder, "index.json"), '{"entries": 3}')
        code, out, err = self.main("list")
        self.assertEqual(code, 0, err)
        self.assertIn("skipping", err)

    # I8
    def test_show_with_cp1252_stdout(self):
        self.make(pages={"guide": "<p>a \u2192 b</p>"})
        env = {"DOCSHELF_CACHE_DIR": self.cache, "PYTHONIOENCODING": "cp1252"}
        r = subprocess.run([sys.executable, SCRIPT, "show", "py:guide"],
                           capture_output=True, env={**clean_env(), **env})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a \u2192 b".encode("utf-8"), r.stdout)


class NotesPageHeadingTests(unittest.TestCase):
    """Notes headings also match headings inside pages (DuckDB indexes whole
    sections, not each function)."""
    UTIL = ("<h2 id='scalar-utility-functions'>Scalar Utility Functions</h2>"
            "<p>Overview.</p>"
            "<h4 id='count_ifx'>count_if(x)</h4><p>Counts true values.</p>"
            "<h4 id='typeofx'>typeof(x)</h4><p>Type name.</p>")
    OTHER = "<h2 id='misc'>Misc</h2><p>Other stuff.</p>"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.notes = os.path.join(self.tmp, "notes")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": self.notes}
        self.folder = make_devdocs(
            self.cache, "duckdb", name="DuckDB", release="1.1.3",
            entries=[("Scalar Utility Functions", "Section",
                      "sql/utility#scalar-utility-functions"),
                     ("Misc", "Section", "sql/other#misc")],
            pages={"sql/utility": self.UTIL, "sql/other": self.OTHER})

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def write_notes(self, text):
        os.makedirs(self.notes, exist_ok=True)
        with open(os.path.join(self.notes, "duckdb.md"), "w", encoding="utf-8") as f:
            f.write(text)

    def test_check_accepts_page_heading_and_lists_its_ref(self):
        self.write_notes("## count_if\nNon-zero counts as true.\n")
        r = self.cli("notes", "duckdb", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("## count_if: shown by show duckdb:sql/utility#count_ifx",
                      r.stdout.splitlines())
        self.assertEqual(r.stdout.splitlines()[-1], "ok")

    def test_show_section_prints_note_for_heading_inside(self):
        self.write_notes("## General\ng\n## count_if\nNon-zero counts as true.\n")
        ref = "duckdb:sql/utility#scalar-utility-functions"
        for r in (self.cli("show", ref), self.cli("show", ref, "--grep", "typeof"),
                  self.cli("show", "duckdb:sql/utility#count_ifx")):
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("## count_if(x)\nNon-zero counts as true.", r.stdout)
            self.assertEqual(r.stdout.count("Non-zero counts as true."), 1)
            self.assertEqual(r.stdout.count("## General"), 1)

    def test_show_unrelated_section_has_no_such_note(self):
        self.write_notes("## General\ng\n## count_if\nNon-zero counts as true.\n")
        r = self.cli("show", "duckdb:sql/other#misc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Non-zero", r.stdout)
        self.assertIn("## General", r.stdout)

    def test_entry_and_heading_match_print_once(self):
        self.write_notes("## Scalar Utility Functions\nentry note\n"
                         "## scalar utility functions (Section)\ntyped\n"
                         "## count_if\nheading note\n")
        r = self.cli("show", "duckdb:sql/utility#scalar-utility-functions")
        self.assertEqual(r.stdout.count("entry note"), 1, r.stdout)
        self.assertEqual(r.stdout.count("typed"), 1, r.stdout)
        self.assertEqual(r.stdout.count("heading note"), 1, r.stdout)
        self.assertLess(r.stdout.index("entry note"), r.stdout.index("heading note"))

    def test_check_warns_for_heading_matching_nothing(self):
        self.write_notes("## nothing_here\nx\n")
        r = self.cli("notes", "duckdb", "--check")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("matches no entry or page heading", r.stdout)
        self.assertNotIn("matches no entry in the docset", r.stdout)

    def test_headings_cache_rebuilt_when_db_changes(self):
        self.write_notes("## count_if\nx\n## sum\ny\n")
        r = self.cli("notes", "duckdb", "--check")
        self.assertIn("warning: section 'sum' matches no entry or page heading",
                      r.stdout)
        cache = os.path.join(self.folder, shelf_devdocs.DERIVED, "headings.json")
        self.assertTrue(os.path.isfile(cache))
        with open(cache, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["stamp"],
                             shelf_devdocs.DevDocsDocset(self.folder).stamp())
        with open(os.path.join(self.folder, "db.json"), encoding="utf-8") as f:
            pages = json.load(f)
        pages["sql/other"] = self.OTHER + "<h3 id='sumx'>sum(x)</h3><p>Adds.</p>"
        with open(os.path.join(self.folder, "db.json"), "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        r = self.cli("notes", "duckdb", "--check")
        self.assertIn("## sum: shown by show duckdb:sql/other#sumx", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_heading_without_id_uses_enclosing_anchor(self):
        shelf_ds = shelf_devdocs.DevDocsDocset(self.folder)
        blocks = shelf_render.html_to_text(
            "<h2 id='a'>A</h2><h4>no_id(x)</h4><h2>Bare</h2>")
        self.assertEqual(shelf_notes.heading_refs(blocks),
                         [("A", "a"), ("no_id(x)", "a"), ("Bare", None)])
        self.assertTrue(shelf_ds.pages())


class GrepDashValueTests(unittest.TestCase):
    PAGE = ("<h2 id='opts'>Options</h2><p>Use --keep to keep changes.</p>"
            "<p>Other text.</p><p>Also other thing.</p>")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        make_devdocs(self.cache, "git", name="Git", release="1",
                     entries=[("git-reset", "Command", "git-reset")],
                     pages={"git-reset": self.PAGE})

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def test_grep_value_starting_with_dash(self):
        r = self.cli("show", "git:git-reset", "--grep", "--keep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Use --keep to keep changes.", r.stdout)
        self.assertNotIn("Other text", r.stdout)

    def test_repeated_dash_grep_and_equals_form(self):
        r = self.cli("show", "git:git-reset", "--grep", "--keep", "--grep", "other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Use --keep", r.stdout)
        self.assertIn("Other text", r.stdout)
        r = self.cli("show", "git:git-reset", "--grep=--keep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Use --keep", r.stdout)

    def test_trailing_bare_grep_is_a_usage_error(self):
        r = self.cli("show", "git:git-reset", "--grep")
        self.assertEqual(r.returncode, 2)
        self.assertIn("expected one argument", r.stderr)


if __name__ == "__main__":
    unittest.main()
