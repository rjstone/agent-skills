"""Offline tests for skills/docshelf. No network: docsets are built by
make_devdocs() in temp dirs. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("docshelf"):
    raise unittest.SkipTest("docshelf not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO_ROOT, "skills", "docshelf")
SCRIPT = os.path.join(SKILL, "scripts", "docshelf.py")

sys.path.insert(0, os.path.join(SKILL, "scripts"))
import shelf_core  # noqa: E402
import shelf_devdocs  # noqa: E402
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
        "version": release, "release": release, "mtime": mtime,
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


if __name__ == "__main__":
    unittest.main()
