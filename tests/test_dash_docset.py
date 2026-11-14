"""Offline tests for skills/dash-docset/scripts/docset.py.

No network: docsets are built by make_docset() in temp dirs. Run from the
repo root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("dash-docset"):
    raise unittest.SkipTest("dash-docset not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "skills", "dash-docset", "scripts", "docset.py")

spec = importlib.util.spec_from_file_location("docset", SCRIPT)
docset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docset)

SUBCOMMANDS = ["where", "sources", "install", "update", "list", "remove",
               "search", "show", "fts", "index-text", "notes"]

DEFAULT_ENTRIES = [
    ("asyncio.gather", "Function", "library/asyncio.html#asyncio.gather"),
    ("asyncio.sleep", "Function", "library/asyncio.html#asyncio.sleep"),
    ("Gather", "Guide", "guide.html"),
]
DEFAULT_PAGES = {
    "library/asyncio.html": (
        "<html><body>\n"
        '<h2 id="asyncio.gather">asyncio.gather</h2>\n'
        "<p>Run awaitables concurrently.</p>\n"
        "<pre>await asyncio.gather(a(), b())</pre>\n"
        '<h2 id="asyncio.sleep">asyncio.sleep</h2>\n'
        "<p>Block for a number of seconds.</p>\n"
        "</body></html>\n"
    ),
    "guide.html": "<html><body><h1>Guide</h1><p>Gather things.</p></body></html>\n",
}


def make_docset(root, name, form="searchIndex", entries=None, pages=None):
    """Build a minimal <name>.docset under root; return its path.

    form is "searchIndex" (plain table) or "ztoken" (Core Data tables)."""
    entries = DEFAULT_ENTRIES if entries is None else entries
    pages = DEFAULT_PAGES if pages is None else pages
    path = os.path.join(root, name + ".docset")
    res = os.path.join(path, "Contents", "Resources")
    docs = os.path.join(res, "Documents")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(path, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleIdentifier": name, "CFBundleName": name,
                       "DocSetPlatformFamily": name.lower()}, f)
    for rel, text in pages.items():
        target = os.path.join(docs, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
    con = sqlite3.connect(os.path.join(res, "docSet.dsidx"))
    try:
        if form == "searchIndex":
            con.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, "
                        "name TEXT, type TEXT, path TEXT)")
            con.executemany("INSERT INTO searchIndex(name, type, path) VALUES (?,?,?)",
                            entries)
        elif form == "ztoken":
            con.executescript(
                "CREATE TABLE ZTOKENTYPE(Z_PK INTEGER PRIMARY KEY, ZTYPENAME TEXT);"
                "CREATE TABLE ZFILEPATH(Z_PK INTEGER PRIMARY KEY, ZPATH TEXT);"
                "CREATE TABLE ZTOKENMETAINFORMATION(Z_PK INTEGER PRIMARY KEY, "
                "ZFILE INTEGER, ZANCHOR TEXT);"
                "CREATE TABLE ZTOKEN(Z_PK INTEGER PRIMARY KEY, ZTOKENNAME TEXT, "
                "ZTOKENTYPE INTEGER, ZMETAINFORMATION INTEGER);")
            types, files = {}, {}
            for i, (tname, ttype, tpath) in enumerate(entries, 1):
                p, _, anchor = tpath.partition("#")
                if ttype not in types:
                    types[ttype] = len(types) + 1
                    con.execute("INSERT INTO ZTOKENTYPE VALUES (?,?)",
                                (types[ttype], ttype))
                if p not in files:
                    files[p] = len(files) + 1
                    con.execute("INSERT INTO ZFILEPATH VALUES (?,?)", (files[p], p))
                con.execute("INSERT INTO ZTOKENMETAINFORMATION VALUES (?,?,?)",
                            (i, files[p], anchor or None))
                con.execute("INSERT INTO ZTOKEN VALUES (?,?,?,?)",
                            (i, tname, types[ttype], i))
        else:
            raise ValueError("unknown form: " + form)
        con.commit()
    finally:
        con.close()
    return path


LEAKY_ENV = ("DASH_DOCSET_DIR", "DASHT_DOCSETS_DIR", "APPDATA", "LOCALAPPDATA")


def clean_env():
    """os.environ without variables that would leak the real store/config."""
    return {k: v for k, v in os.environ.items()
            if k not in LEAKY_ENV and not k.startswith("XDG_")}


def run_cli(*args, env=None, cwd=None):
    full_env = clean_env()
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True,
                          text=True, env=full_env, cwd=cwd)


class SkeletonTests(unittest.TestCase):
    def test_help_lists_subcommands(self):
        r = run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in SUBCOMMANDS:
            self.assertIn(name, r.stdout)

    def test_version(self):
        import re
        self.assertRegex(docset.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(docset.USER_AGENT, f"dash-docset/{docset.VERSION}")
        r = run_cli("--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(docset.VERSION, r.stdout)
        self.assertIn(docset.VERSION, run_cli("--help").stdout)
        # The script may lag SKILL.md's version but never lead it.
        skill_md = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "SKILL.md")
        with open(skill_md, encoding="utf-8") as f:
            m = re.search(r'^\s*version:\s*"(\d+)\.(\d+)\.(\d+)"', f.read(), re.M)
        self.assertIsNotNone(m)
        skill = tuple(int(x) for x in m.groups())
        script = tuple(int(x) for x in docset.VERSION.split("."))
        self.assertLessEqual(script, skill)

    def test_allowlist_covers_script_hosts(self):
        from urllib.parse import urlsplit
        path = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "assets",
                            "allowlist.txt")
        with open(path, encoding="utf-8") as f:
            listed = {l.strip() for l in f if l.strip() and not l.startswith("#")}
        used = {urlsplit(v).hostname for k, v in vars(docset).items()
                if k.endswith("_URL") and isinstance(v, str) and "://" in v}
        self.assertTrue(used)
        self.assertEqual(used - listed, set())

    def test_fixture_both_forms(self):
        import tempfile
        for form in ("searchIndex", "ztoken"):
            with self.subTest(form=form), tempfile.TemporaryDirectory() as d:
                path = make_docset(d, "Python_3", form=form)
                res = os.path.join(path, "Contents", "Resources")
                self.assertTrue(os.path.isfile(os.path.join(res, "docSet.dsidx")))
                self.assertTrue(os.path.isfile(os.path.join(path, "Contents", "Info.plist")))
                self.assertTrue(os.path.isfile(
                    os.path.join(res, "Documents", "library", "asyncio.html")))


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.home = os.path.join(self.tmp, "home")
        self.proj = os.path.join(self.tmp, "proj")
        self.sub = os.path.join(self.proj, "a", "b")
        for d in (self.home, self.sub):
            os.makedirs(d)
        self.env = {"HOME": self.home, "USERPROFILE": self.home,
                    "XDG_CONFIG_HOME": os.path.join(self.home, "cfg"),
                    "XDG_DATA_HOME": os.path.join(self.home, "data")}
        self.user_cfg = os.path.join(self.env["XDG_CONFIG_HOME"],
                                     "dash-docset", "config.json")

    def write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def cli_env(self):
        return dict(self.env)

    def test_resolve_order(self):
        r = docset.resolve_store
        self.assertIsNone(r(None, self.sub, self.env))
        self.write_json(self.user_cfg, {"store": "/user/store"})
        st = r(None, self.sub, self.env)
        self.assertEqual((st.path, st.source), (os.path.abspath("/user/store"), "user config"))
        self.write_json(os.path.join(self.proj, ".dash-docset.json"),
                        {"store": "/proj/store"})
        st = r(None, self.sub, self.env)
        self.assertEqual(st.path, os.path.abspath("/proj/store"))
        self.assertEqual(st.source, "project file")
        env2 = dict(self.env, DASH_DOCSET_DIR="/env/store")
        st = r(None, self.sub, env2)
        self.assertEqual((st.path, st.source), (os.path.abspath("/env/store"), "DASH_DOCSET_DIR"))
        st = r("/cli/store", self.sub, env2)
        self.assertEqual((st.path, st.source), (os.path.abspath("/cli/store"), "--dir"))

    def test_project_file_relative_paths(self):
        self.write_json(os.path.join(self.proj, ".dash-docset.json"),
                        {"store": ".docsets", "read_from": ["../shared", "/abs/x"],
                         "docsets": ["Python_3"]})
        st = docset.resolve_store(None, self.sub, self.env)
        self.assertEqual(st.path, os.path.join(self.proj, ".docsets"))
        self.assertEqual(st.read_from, [os.path.normpath(os.path.join(self.tmp, "shared")),
                                        os.path.abspath("/abs/x")])
        self.assertEqual(st.project_docsets, ["Python_3"])

    def test_user_config_read_from(self):
        self.write_json(self.user_cfg, {"store": "/s", "read_from": ["/r"]})
        st = docset.resolve_store(None, self.sub, self.env)
        self.assertEqual(st.read_from, [os.path.abspath("/r")])
        self.assertIsNone(st.project_docsets)

    def test_explicit_dir_ignores_malformed_config(self):
        os.makedirs(os.path.dirname(self.user_cfg))
        with open(self.user_cfg, "w") as f:
            f.write("{not json")
        with open(os.path.join(self.proj, ".dash-docset.json"), "w") as f:
            f.write("[]")
        st = docset.resolve_store("/cli/store", self.sub, self.env)
        self.assertEqual(st.source, "--dir")
        st = docset.resolve_store(None, self.sub, dict(self.env, DASH_DOCSET_DIR="/e"))
        self.assertEqual(st.source, "DASH_DOCSET_DIR")
        with self.assertRaises(docset.CLIError):  # the config in use is malformed
            docset.resolve_store(None, self.sub, self.env)

    def test_malformed_user_config_ignored_when_project_wins(self):
        os.makedirs(os.path.dirname(self.user_cfg))
        with open(self.user_cfg, "w") as f:
            f.write("{not json")
        self.write_json(os.path.join(self.proj, ".dash-docset.json"), {"store": "s"})
        self.assertEqual(docset.resolve_store(None, self.sub, self.env).source,
                         "project file")

    def test_explicit_dir_keeps_read_from_and_project_docsets(self):
        self.write_json(self.user_cfg, {"store": "/u", "read_from": ["/user/ro"]})
        st = docset.resolve_store("/cli", self.sub, self.env)
        self.assertEqual(st.read_from, [os.path.abspath("/user/ro")])
        self.write_json(os.path.join(self.proj, ".dash-docset.json"),
                        {"read_from": ["../ro"], "docsets": ["X"]})
        st = docset.resolve_store(None, self.sub, dict(self.env, DASH_DOCSET_DIR="/e"))
        self.assertEqual(st.read_from, [os.path.normpath(os.path.join(self.tmp, "ro"))])
        self.assertEqual(st.project_docsets, ["X"])

    def test_discover(self):
        dasht = os.path.join(self.env["XDG_DATA_HOME"], "dasht", "docsets")
        os.makedirs(dasht)
        zeal = os.path.join(self.home, ".local", "share", "Zeal", "Zeal", "docsets")
        os.makedirs(zeal)
        found = docset.discover(self.env)
        self.assertEqual(found, [dasht, zeal])
        self.assertEqual(docset.discover(dict(self.env, HOME=self.tmp,
                                              USERPROFILE=self.tmp,
                                              XDG_DATA_HOME=self.tmp)), [])

    def test_viewer_apps_and_zeal_conf(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        exe = os.path.join(bin_dir, "zeal")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(exe, 0o755)
        env = dict(self.env, PATH=bin_dir)
        if sys.platform != "win32":
            self.assertIn(("Zeal", exe), docset.viewer_apps(env))
        flat = os.path.join(self.env["HOME"], ".var", "app", "org.zealdocs.Zeal")
        os.makedirs(flat)
        self.assertIn(("Zeal", flat), docset.viewer_apps(dict(self.env, PATH="")))
        custom = os.path.join(self.tmp, "my-docsets")
        os.makedirs(custom)
        conf = os.path.join(self.env["HOME"], ".config", "Zeal", "Zeal.conf")
        os.makedirs(os.path.dirname(conf))
        with open(conf, "w") as f:
            f.write("[docsets]\npath=%s\n" % custom)
        env = dict(self.env)
        env.pop("XDG_CONFIG_HOME", None)
        self.assertIn(custom, docset.discover(env))
        r = run_cli("where", "--discover", env=dict(self.cli_env(), PATH=""), cwd=self.sub)
        self.assertIn("app: Zeal", r.stdout)

    def test_zeal_paths_macos_and_portable(self):
        home = self.env["HOME"]
        mac = os.path.join(home, "Library", "Application Support", "Zeal", "Zeal", "docsets")
        os.makedirs(mac)
        self.assertIn(mac, docset.discover(dict(self.env, PATH="")))
        custom = os.path.join(self.tmp, "mac-custom")
        os.makedirs(custom)
        prefs = os.path.join(home, "Library", "Preferences")
        os.makedirs(prefs)
        with open(os.path.join(prefs, "org.zealdocs.Zeal.plist"), "wb") as f:
            plistlib.dump({"docsets.path": custom}, f)
        self.assertIn(custom, docset._zeal_custom_paths(self.env))
        app_dir = os.path.join(self.tmp, "ZealPortable")
        os.makedirs(os.path.join(app_dir, "docs"))
        with open(os.path.join(app_dir, "zeal.ini"), "w") as f:
            f.write("[docsets]\npath=docs\n")
        exe = os.path.join(app_dir, "zeal.exe")
        self.assertIn(os.path.join(app_dir, "docs"),
                      docset._zeal_custom_paths(self.env, [("Zeal", exe)]))

    def test_unset_exits_3_and_lists_discovered(self):
        dasht = os.path.join(self.env["XDG_DATA_HOME"], "dasht", "docsets")
        os.makedirs(dasht)
        r = run_cli("where", env=self.cli_env(), cwd=self.sub)
        self.assertEqual(r.returncode, 3, r.stderr)  # same code as other commands
        self.assertIn("not set", r.stdout)
        r = run_cli("where", "--discover", env=self.cli_env(), cwd=self.sub)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(dasht, r.stdout)
        # require_store: exit 3 with the same hints on stderr
        with self.assertRaises(docset.CLIError) as cm:
            docset.require_store(
                type("A", (), {"dir": None})(), cwd=self.sub, env=self.env)
        self.assertEqual(cm.exception.code, 3)
        self.assertIn("storage location not set", str(cm.exception))
        self.assertIn(dasht, str(cm.exception))

    def test_where_reports_store(self):
        r = run_cli("--dir", "mystore", "where", env=self.cli_env(), cwd=self.sub)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(os.path.join(self.sub, "mystore"), r.stdout)
        self.assertIn("--dir", r.stdout)

    def test_set_project_writes_gitignore(self):
        r = run_cli("where", "--set", ".docsets", "--project", "--read-from",
                    "../shared", env=self.cli_env(), cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.proj, ".dash-docset.json")) as f:
            data = json.load(f)
        self.assertEqual(data, {"store": ".docsets", "read_from": ["../shared"]})
        with open(os.path.join(self.proj, ".docsets", ".gitignore")) as f:
            self.assertEqual(f.read().split(), ["*", "!.gitignore", "!notes/", "!notes/**"])
        r = run_cli("where", env=self.cli_env(), cwd=self.sub)
        self.assertIn(os.path.join(self.proj, ".docsets"), r.stdout)

    def test_set_project_other_name_no_gitignore(self):
        r = run_cli("where", "--set", "store", "--project",
                    env=self.cli_env(), cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "store", ".gitignore")))

    def test_set_user(self):
        target = os.path.join(self.tmp, "mine")
        r = run_cli("where", "--set", target, "--user", env=self.cli_env(), cwd=self.sub)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.user_cfg) as f:
            self.assertEqual(json.load(f), {"store": target})

    def test_set_requires_scope(self):
        r = run_cli("where", "--set", "x", env=self.cli_env(), cwd=self.sub)
        self.assertNotEqual(r.returncode, 0)


def tmp_dir(case):
    t = tempfile.TemporaryDirectory()
    case.addCleanup(t.cleanup)
    return os.path.realpath(t.name)


def entries_of(ds):
    return [(n, t, p) for _i, n, t, p in docset.iter_entries(ds)]


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        self.ro = os.path.join(self.tmp, "ro")
        os.makedirs(self.store_dir)
        os.makedirs(self.ro)

    def store(self, read_from=()):
        return docset.Store(self.store_dir, "--dir", list(read_from), None)

    def by_name(self, docs):
        return {d.name: d for d in docs}

    def test_iter_entries_both_forms(self):
        for form in ("searchIndex", "ztoken"):
            with self.subTest(form=form):
                d = os.path.join(self.tmp, form)
                os.makedirs(d)
                path = make_docset(d, "Py", form=form)
                ds = docset.Docset("Py", path, False, None, None, 3)
                rows = list(docset.iter_entries(ds))
                self.assertEqual([r[1:] for r in rows], DEFAULT_ENTRIES)
                self.assertTrue(all(isinstance(r[0], int) for r in rows))

    def test_find_docsets_store_metadata_and_foreign(self):
        make_docset(self.store_dir, "Py")
        make_docset(self.ro, "Other", form="ztoken")
        docset.save_installed(self.store(), {"Py": {"source": "kapeli", "version": "1.2"}})
        docs = self.by_name(docset.find_docsets(self.store([self.ro])))
        self.assertEqual(set(docs), {"Py", "Other"})
        self.assertEqual((docs["Py"].foreign, docs["Py"].source, docs["Py"].version,
                          docs["Py"].entry_count), (False, "kapeli", "1.2", 3))
        self.assertEqual((docs["Other"].foreign, docs["Other"].source,
                          docs["Other"].entry_count), (True, None, 3))

    def test_foreign_nested_depth_two(self):
        nested = os.path.join(self.ro, "Dir")
        os.makedirs(nested)
        make_docset(nested, "Deep")
        docs = docset.find_docsets(self.store([self.ro]))
        self.assertEqual([d.name for d in docs], ["Deep"])

    def test_installed_json_roundtrip(self):
        st = self.store()
        self.assertEqual(docset.load_installed(st), {})
        docset.save_installed(st, {"A": {"version": "1"}})
        self.assertEqual(docset.load_installed(st), {"A": {"version": "1"}})
        self.assertEqual(docset.meta_dir(st), os.path.join(self.store_dir, ".dash-docset"))
        self.assertEqual(os.listdir(docset.meta_dir(st)), ["installed.json"])

    def test_list_marks_foreign_and_clash(self):
        make_docset(self.store_dir, "Py")
        make_docset(self.ro, "Py")
        make_docset(self.ro, "Other")
        docset.save_installed(self.store(), {"Py": {"source": "kapeli", "version": "9"}})
        r = run_cli("--dir", self.store_dir, "list", env={"HOME": self.tmp},
                    cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = {l.split()[0]: l for l in r.stdout.splitlines()}
        self.assertIn("kapeli", lines["Py"])
        self.assertIn("9", lines["Py"])
        self.assertNotIn("foreign", lines["Py"])
        # read_from comes from config; use the project file here
        with open(os.path.join(self.tmp, ".dash-docset.json"), "w") as f:
            json.dump({"read_from": ["ro"]}, f)
        r = run_cli("--dir", self.store_dir, "list", env={"HOME": self.tmp},
                    cwd=self.tmp)
        lines = {l.split()[0]: l for l in r.stdout.splitlines()}
        self.assertIn("foreign (%s)" % self.ro, lines["Other"])
        self.assertIn("also in", lines["Py"])
        self.assertIn(self.ro, lines["Py"])
        self.assertNotIn("foreign", lines["Py"].split("also in")[0])
        self.assertEqual(len(lines), 2)

    def test_full_size_rule(self):
        D = docset.Docset
        self.assertFalse(D("c", "p", False, "cheat", "1", 9999).full_size)
        self.assertFalse(D("f", "p", True, None, None, 3).full_size)
        self.assertTrue(D("f", "p", True, None, None, 500).full_size)
        self.assertTrue(D("k", "p", False, "kapeli", "1", 3).full_size)
        self.assertFalse(D("u", "p", False, None, None, 3).full_size)  # Ruling 1
        self.assertTrue(D("u", "p", False, None, None, 600).full_size)

    def test_unreadable_docset_skipped(self):
        make_docset(self.store_dir, "Good")
        bad = make_docset(self.store_dir, "Bad")
        open(os.path.join(bad, "Contents", "Resources", "docSet.dsidx"), "w").close()
        r = run_cli("--dir", self.store_dir, "list", env={"HOME": self.tmp}, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Good", r.stdout)
        self.assertNotIn("Bad", r.stdout)
        self.assertIn("Bad", r.stderr)
        self.assertIn("warning", r.stderr)


class NavSkipTests(unittest.TestCase):
    def test_navigation_chrome_dropped(self):
        html = ('<div class="related" role="navigation"><h3>Navigation</h3>'
                '<ul><li>index</li><li><div>nested</div></li></ul></div>'
                '<div class="mobile-nav"><form><input></form>'
                '<select><option>Dark</option></select></div>'
                '<div role="main"><h1 id="t">Title<a class="headerlink">\u00b6</a></h1>'
                '<p>Body</p></div><div role="search">Quick search</div>')
        text = [b.text for b in docset.html_to_text(html)]
        self.assertEqual(text, ["# Title", "Body"])


class RankTests(unittest.TestCase):
    def test_rank_order(self):
        r = docset.rank
        self.assertEqual(r("Gather", "gather"), 0)
        self.assertEqual(r("gat", "Gather"), 1)
        self.assertEqual(r("ath", "Gather"), 2)
        self.assertEqual(r("gtr", "Gather"), 3)
        self.assertIsNone(r("xyz", "Gather"))
        self.assertIsNone(r("rg", "Gather"))  # order matters

    def test_parse_ref(self):
        self.assertEqual(docset.parse_ref("Python_3:42"), ("Python_3", 42))
        self.assertEqual(docset.parse_ref("A:B:7"), ("A:B", 7))
        for bad in ("nocolon", "A:x", ":3", "A:", "x:" + chr(0xb2), "x:" + chr(0x663)):
            with self.subTest(bad=bad), self.assertRaises(docset.CLIError):
                docset.parse_ref(bad)

    def test_cap_lines(self):
        lines = ["l%d" % i for i in range(10)]
        self.assertEqual(docset.cap_lines(lines, 10, "h"), lines)
        out = docset.cap_lines(lines, 4, "use --x")
        self.assertEqual(out[:4], lines[:4])
        self.assertEqual(out[4], "... 6 more lines cut; use --x")
        self.assertEqual(len(out), 5)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)
        self.installed = {}

    def add(self, name, entries=None, source="kapeli", form="searchIndex"):
        make_docset(self.store_dir, name, form=form, entries=entries)
        if source:
            self.installed[name] = {"source": source, "version": "1"}
        docset.save_installed(docset.Store(self.store_dir, "--dir", [], None),
                              self.installed)

    def cli(self, *args, project=None):
        if project is not None:
            with open(os.path.join(self.tmp, ".dash-docset.json"), "w") as f:
                json.dump(project, f)
        return run_cli("--dir", self.store_dir, *args, env={"HOME": self.tmp},
                       cwd=self.tmp)

    def test_search_ranks_across_docsets(self):
        self.add("Alpha", [("sleep_long", "Function", "a.html"),
                           ("sleep", "Function", "b.html")])
        self.add("Beta", [("Sleep", "Guide", "c.html"), ("xsleepx", "Guide", "d.html"),
                          ("s_l_e_e_p", "Guide", "e.html")], form="ztoken")
        r = self.cli("search", "sleep")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out[4], "--- fuzzy matches (letters in order, often unrelated) ---")
        names = [l.split("  ")[2] for l in out if not l.startswith("---")]
        self.assertEqual(names, ["Sleep", "sleep", "sleep_long", "xsleepx", "s_l_e_e_p"])
        r = self.cli("search", "slp", "-d", "Alpha")
        self.assertTrue(r.stdout.startswith("no exact, prefix or substring matches"))
        r = self.cli("search", "qqq", "-d", "Alpha")
        self.assertEqual(r.stdout.strip(), "no matches for 'qqq'")
        first = out[0].split("  ")
        self.assertEqual(first[1], "Guide")
        self.assertEqual(first[3], "(Beta)")
        self.assertRegex(first[0], r"^Beta:\d+$")
        self.assertTrue(out[1].startswith("Alpha:2  "))

    def test_search_type_filter_case_insensitive(self):
        self.add("Alpha", [("sleep", "Function", "a.html"), ("sleep2", "Guide", "b.html")])
        r = self.cli("search", "sleep", "--type", "guide")
        self.assertEqual(len(r.stdout.splitlines()), 1)
        self.assertIn("sleep2", r.stdout)

    def test_search_like_wildcards_escaped(self):
        self.add("Alpha", [("a_c", "Function", "a.html"), ("abc", "Function", "b.html"),
                           ("100%", "Function", "c.html")])
        r = self.cli("search", "a_c")
        self.assertEqual([l.split("  ")[2] for l in r.stdout.splitlines()], ["a_c"])
        r = self.cli("search", "%")
        self.assertEqual([l.split("  ")[2] for l in r.stdout.splitlines()], ["100%"])

    def test_unknown_docset_exits_4(self):
        self.add("Alpha")
        r = self.cli("search", "x", "-d", "Nope")
        self.assertEqual(r.returncode, 4)
        self.assertIn("Nope", r.stderr)

    def test_scope_names_beat_project(self):
        self.add("Alpha", [("thing", "Function", "a.html")])
        self.add("Beta", [("thing", "Function", "b.html")])
        r = self.cli("search", "thing", "-d", "Beta", project={"docsets": ["Alpha"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(Beta)", r.stdout)
        self.assertNotIn("(Alpha)", r.stdout)

    def test_scope_project_list(self):
        for n in "ABCDEF":
            self.add("Doc" + n, [("thing", "Function", "a.html")])
        r = self.cli("search", "thing", project={"docsets": ["DocB", "DocC"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(l.split("  ")[3] for l in r.stdout.splitlines()),
                         ["(DocB)", "(DocC)"])

    def test_scope_error_over_four_full(self):
        for n in "ABCDE":
            self.add("Doc" + n, [("thing", "Function", "a.html")])
        r = self.cli("search", "thing")
        self.assertEqual(r.returncode, 4)
        for n in "ABCDE":
            self.assertIn("Doc" + n, r.stderr)
        for hint in ("-d", "docsets", ".dash-docset.json", "--all"):
            self.assertIn(hint, r.stderr)
        r = self.cli("search", "thing", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 5)

    def test_scope_small_docsets_dont_count(self):
        for n in "ABCD":
            self.add("Doc" + n, [("thing", "Function", "a.html")])
        for n in "XYZ":
            self.add("Cheat" + n, [("thing", "Function", "a.html")], source="cheat")
        r = self.cli("search", "thing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 7)

    def test_search_max_lines_and_hint(self):
        self.add("Alpha", [("item%02d" % i, "Function", "a.html") for i in range(50)])
        r = self.cli("search", "item")
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 41)
        self.assertTrue(lines[-1].startswith("... 10 more lines cut;"), lines[-1])
        self.assertIn("--max-lines", lines[-1])
        r = self.cli("search", "item", "--max-lines", "5")
        self.assertEqual(len(r.stdout.splitlines()), 6)

    def test_search_json(self):
        self.add("Alpha", [("sleep", "Function", "a.html"), ("sleeper", "Guide", "b.html")])
        r = self.cli("search", "sleep", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual([d["name"] for d in data], ["sleep", "sleeper"])
        self.assertEqual(set(data[0]), {"ref", "docset", "type", "name", "rank"})
        self.assertEqual((data[0]["docset"], data[0]["rank"], data[1]["rank"]),
                         ("Alpha", 0, 1))
        self.assertEqual(data[0]["ref"], "Alpha:1")
        r = self.cli("search", "sleep", "--json", "--max-lines", "1")
        self.assertEqual(len(json.loads(r.stdout)), 1)

    def test_search_skips_broken_docset_with_warning(self):
        self.add("Good", [("thing", "Function", "a.html")])
        self.add("Bad", [("thing", "Function", "a.html")])
        con = sqlite3.connect(os.path.join(self.store_dir, "Bad.docset", "Contents",
                                           "Resources", "docSet.dsidx"))
        con.execute("DROP TABLE searchIndex")
        con.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, x TEXT)")
        con.commit()
        con.close()
        r = self.cli("search", "thing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(Good)", r.stdout)
        self.assertIn("Bad", r.stderr)


    def test_max_lines_below_one_rejected(self):
        self.add("Alpha", [("sleep", "Function", "a.html")])
        for cmd in (("search", "sleep"), ("show", "Alpha:1")):
            for bad in ("0", "-3", "x"):
                with self.subTest(cmd=cmd[0], bad=bad):
                    r = self.cli(*cmd, "--max-lines", bad)
                    self.assertEqual(r.returncode, 2, r.stderr)


GIT_PAGE = (
    "<html><body><table>\n"
    "<tr id='//dash_ref_Create/Entry/Clone an existing repository/0'>"
    "<td><p>Clone an existing repository</p></td><td><code>git clone URL</code></td></tr>\n"
    "<tr id='//dash_ref_Create/Entry/Create a new repository/0'>"
    "<td><p>Create a new repository</p></td><td><code>git init</code></td></tr>\n"
    "</table></body></html>\n")
PY_PAGE = (
    '<html><body><dl class="py">\n'
    '<dt id="asyncio.gather">gather(*aws)</dt><dd><p>Run them together.</p></dd>\n'
    '<dt id="asyncio.sleep">sleep(delay)</dt><dd><p>Block a while.</p></dd>\n'
    "</dl></body></html>\n")


class ShowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)

    def add(self, name, entries, pages):
        make_docset(self.store_dir, name, entries=entries, pages=pages)

    def cli(self, *args):
        return run_cli("--dir", self.store_dir, *args, env={"HOME": self.tmp},
                       cwd=self.tmp)

    def test_show_trims_to_anchor(self):
        self.add("Py", DEFAULT_ENTRIES, DEFAULT_PAGES)
        r = self.cli("show", "Py:1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("asyncio.gather", r.stdout)
        self.assertIn("await asyncio.gather(a(), b())", r.stdout)
        self.assertIn("Run awaitables concurrently.", r.stdout)
        self.assertNotIn("asyncio.sleep", r.stdout)
        self.assertNotIn("Block for", r.stdout)
        self.assertTrue(r.stdout.startswith("## ") or "\n## " in r.stdout)
        r = self.cli("show", "Py:3")  # no anchor: whole page
        self.assertIn("# Guide", r.stdout)
        r = self.cli("show", "Py:1", "--full")
        self.assertIn("Run awaitables concurrently.", r.stdout)
        self.assertNotIn("Block for", r.stdout)

    def test_show_full_lifts_cap_on_long_section(self):
        body = "".join("<p>row %d</p>" % i for i in range(300))
        self.add("L", [("sec", "Section", "p.html#s")],
                 {"p.html": "<h2 id='s'>Sec</h2>" + body + "<h2 id='t'>Next</h2><p>other</p>"})
        r = self.cli("show", "L:1")
        self.assertEqual(len(r.stdout.splitlines()), 151)
        r = self.cli("show", "L:1", "--full")
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 301)
        self.assertNotIn("other", r.stdout)

    def test_show_tr_and_dt_anchors(self):
        self.add("Git", [("Clone", "Entry",
                          "index.html#//dash_ref_Create/Entry/Clone%20an%20existing%20repository/0"),
                         ("Create", "Entry",
                          "index.html#//dash_ref_Create/Entry/Create%20a%20new%20repository/0")],
                 {"index.html": GIT_PAGE})
        r = self.cli("show", "Git:1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("git clone URL", r.stdout)
        self.assertNotIn("git init", r.stdout)
        self.assertNotIn("not found", r.stdout)
        r = self.cli("show", "Git:2")
        self.assertIn("git init", r.stdout)
        self.assertNotIn("git clone", r.stdout)
        self.add("PyDoc", [("asyncio.gather", "Function", "a.html#asyncio.gather"),
                           ("asyncio.sleep", "Function", "a.html#asyncio.sleep")],
                 {"a.html": PY_PAGE})
        r = self.cli("show", "PyDoc:1")
        self.assertIn("gather(*aws)", r.stdout)
        self.assertIn("Run them together.", r.stdout)
        self.assertNotIn("sleep", r.stdout)

    def test_show_anchor_not_found_shows_page_with_note(self):
        self.add("Py", [("x", "Function", "guide.html#nope")], DEFAULT_PAGES)
        r = self.cli("show", "Py:1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("anchor not found", r.stdout)
        self.assertIn("Gather things.", r.stdout)

    def test_entry_location(self):
        el = docset.entry_location
        self.assertEqual(el("a/b.html#x"), ("a/b.html", "x"))
        self.assertEqual(el("a/b.html"), ("a/b.html", None))
        self.assertEqual(el("a%20b.html#x%20y"), ("a b.html", "x%20y"))
        self.assertEqual(el("<dash_entry_name=Foo><dash_entry_isSuper=1>a/b.html#x"),
                         ("a/b.html", "x"))

    def test_show_path_variants(self):
        pages = {"my dir/p age.html": "<h1 id='top'>Top</h1><p>body text</p>"}
        self.add("D", [("m", "Guide", "<dash_entry_name=m>my%20dir/p%20age.html#top"),
                       ("n", "Guide", "my%20dir/p%20age.html")], pages)
        for ref in ("D:1", "D:2"):
            r = self.cli("show", ref)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("body text", r.stdout)

    def test_show_online_only(self):
        self.add("D", [("m", "Guide", "https://example.com/doc#x")], {})
        r = self.cli("show", "D:1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("online-only entry: https://example.com/doc#x", r.stdout)

    def test_show_bad_encoding_and_cap(self):
        self.add("D", [("big", "Guide", "big.html"), ("lat", "Guide", "lat.html")], {})
        docs = os.path.join(self.store_dir, "D.docset", "Contents", "Resources",
                            "Documents")
        with open(os.path.join(docs, "big.html"), "w", encoding="utf-8") as f:
            f.write("<body>" + "".join("<p>line %d</p>" % i for i in range(1000))
                    + "</body>")
        with open(os.path.join(docs, "lat.html"), "wb") as f:
            f.write("<p>caf\xe9 ok</p>".encode("latin-1"))
        r = self.cli("show", "D:1")
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 151)
        self.assertIn("850 more lines cut", lines[-1])
        self.assertIn("--full", lines[-1])
        r = self.cli("show", "D:1", "--full")
        self.assertEqual(len(r.stdout.splitlines()), 1000)
        r = self.cli("show", "D:1", "--max-lines", "10")
        self.assertEqual(len(r.stdout.splitlines()), 11)
        r = self.cli("show", "D:2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_show_unknown_ref(self):
        self.add("D", [("m", "Guide", "gone.html")], {})
        r = self.cli("show", "D:99")
        self.assertEqual(r.returncode, 5)
        self.assertIn("D:99", r.stderr)
        r = self.cli("show", "Nope:1")
        self.assertEqual(r.returncode, 5)
        self.assertIn("Nope", r.stderr)
        r = self.cli("show", "D:1")  # page file missing
        self.assertEqual(r.returncode, 5)
        self.assertIn("gone.html", r.stderr)
        r = self.cli("show", "garbage")
        self.assertEqual(r.returncode, 2)

    def test_html_to_text_blocks(self):
        html = ("<nav>skip me</nav><script>x=1</script><h2 id='a'>Title</h2>"
                "<ul><li>one</li><li>two</li></ul>"
                "<pre>  x = 1\n  y = 2</pre><footer>bye</footer>")
        blocks = docset.html_to_text(html)
        texts = [b.text for b in blocks]
        self.assertEqual(texts[0], "## Title")
        self.assertEqual(blocks[0].level, 2)
        self.assertEqual(blocks[0].ids, ["a"])
        self.assertEqual(texts[1:3], ["- one", "- two"])
        self.assertEqual(blocks[1].depth, 1)
        self.assertEqual(texts[3], "```\n  x = 1\n  y = 2\n```")
        self.assertNotIn("skip", "".join(texts))
        self.assertNotIn("bye", "".join(texts))


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)

    def cli(self, *args):
        return run_cli("--dir", self.store_dir, *args, env={"HOME": self.tmp},
                       cwd=self.tmp)

    def write_notes(self, name, text):
        path = docset.notes_path(self.store_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_notes_path_creates_dir_and_check_ok(self):
        make_docset(self.store_dir, "Py")
        r = self.cli("notes", "Py", "--path")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.dirname(r.stdout.strip())))
        self.write_notes("Py", "## General\nok\n")
        r = self.cli("notes", "Py", "--check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.startswith("ok: "))

    def test_notes_output_keeps_headings(self):
        self.write_notes("Py", "gen\n## asyncio.gather (Function)\nfn\n")
        out = docset.notes_for(self.store_dir, "Py", "asyncio.gather", "Function")
        self.assertEqual(out[1:], ["## General", "gen",
                                   "## asyncio.gather (Function)", "fn"])
        self.assertEqual(docset.general_notes(self.store_dir, "Py")[1:],
                         ["## General", "gen"])

    def test_notes_path(self):
        self.assertEqual(docset.notes_path(self.store_dir, "Py"),
                         os.path.join(self.store_dir, "notes", "Py.md"))

    def test_parse_notes(self):
        general, sections = docset.parse_notes(
            "# Title\nintro\n## Asyncio.Gather (Function)\nA\n## other\nB\n"
            "## General\nG2\n")
        self.assertEqual(general, ["intro", "G2"])
        self.assertEqual(sections["asyncio.gather"], [("Function", ["A"])])
        self.assertEqual(sections["other"], [(None, ["B"])])
        self.assertNotIn("general", sections)

    def test_notes_match_case_and_type(self):
        self.write_notes("Py", "gen line\n## ASYNCIO.gather (function)\nfn note\n"
                         "## asyncio.gather (Guide)\nguide note\n"
                         "## asyncio.gather\nany note\n## unrelated\nnope\n")
        out = "\n".join(docset.notes_for(self.store_dir, "Py", "Asyncio.Gather",
                                         "Function"))
        self.assertIn("--- notes (", out)
        self.assertIn("gen line", out)
        self.assertIn("fn note", out)
        self.assertIn("any note", out)
        self.assertNotIn("guide note", out)
        self.assertNotIn("nope", out)
        self.assertEqual(docset.notes_for(self.store_dir, "Nofile", "x", "y"), [])

    def test_notes_shown_with_show(self):
        make_docset(self.store_dir, "Py")
        self.write_notes("Py", "general tip\n## asyncio.gather\nuse return_exceptions\n")
        r = self.cli("show", "Py:1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Run awaitables concurrently.", r.stdout)
        self.assertIn("use return_exceptions", r.stdout)
        self.assertIn("general tip", r.stdout)
        r = self.cli("show", "Py:1", "--no-notes")
        self.assertNotIn("use return_exceptions", r.stdout)
        r = self.cli("search", "gather", "-d", "Py")
        self.assertNotIn("general tip", r.stdout)  # notes only with show
        self.assertNotIn("use return_exceptions", r.stdout)
        r = self.cli("search", "gather", "-d", "Py", "--json")
        self.assertNotIn("general tip", r.stdout)
        json.loads(r.stdout)

    def test_show_warns_on_size_only(self):
        make_docset(self.store_dir, "Py")
        self.write_notes("Py", "## asyncio.gather\n" + "x\n" * 250
                         + "## orphan heading\ny\n")
        r = self.cli("show", "Py:1")
        self.assertIn("asyncio.gather", r.stderr)
        self.assertNotIn("orphan heading", r.stderr)

    def test_notes_for_foreign_docset_live_in_store(self):
        foreign = os.path.join(self.tmp, "foreign")
        os.makedirs(foreign)
        make_docset(foreign, "Ext")
        before = sorted(os.path.join(d, f) for d, _, fs in os.walk(foreign) for f in fs)
        with open(os.path.join(self.tmp, ".dash-docset.json"), "w") as f:
            json.dump({"read_from": [foreign]}, f)
        r = self.cli("notes", "Ext", "--path")
        self.assertEqual(r.returncode, 0, r.stderr)
        path = r.stdout.strip()
        self.assertEqual(path, os.path.join(self.store_dir, "notes", "Ext.md"))
        self.assertFalse(os.path.exists(path))
        self.write_notes("Ext", "hello\n")
        r = self.cli("notes", "Ext")
        self.assertIn("hello", r.stdout)
        after = sorted(os.path.join(d, f) for d, _, fs in os.walk(foreign) for f in fs)
        self.assertEqual(before, after)

    def test_check_limits(self):
        w = docset.check_notes("## a\n" + "x\n" * 250, {"a"})
        self.assertTrue(any("'a'" in x and "100" in x for x in w), w)
        text = "".join("## s%d\n%s" % (i, "x\n" * 9) for i in range(100))
        names = {"s%d" % i for i in range(100)}
        self.assertEqual(docset.check_notes(text, names), [])
        self.assertTrue(docset.check_notes("x\n" * 51, set()))
        big = "".join("## t%d\n%s" % (i, "x\n" * 99) for i in range(21))
        w = docset.check_notes(big, {"t%d" % i for i in range(21)})
        self.assertTrue(any("2,000" in x or "2000" in x for x in w), w)

    def test_parenthesised_entry_names(self):
        make_docset(self.store_dir, "C", entries=[
            ("strlen()", "Function", "s.html#strlen")],
            pages={"s.html": '<h2 id="strlen">strlen</h2><p>Length.</p>'})
        self.write_notes("C", "## strlen()\nnul-terminated only\n")
        r = self.cli("show", "C:1")
        self.assertIn("nul-terminated only", r.stdout)
        self.assertEqual(self.cli("notes", "C", "--check").returncode, 0)
        self.assertEqual(docset.parse_notes("## f (Type)\nx\n")[1]["f"][0][0], "Type")

    def test_title_after_blank_lines_is_not_general(self):
        general, _ = docset.parse_notes("\n\n# Title\nintro\n")
        self.assertEqual(general, ["intro"])

    def test_check_orphans(self):
        w = docset.check_notes("## real\nx\n## ghost (Type)\ny\n", {"real"})
        self.assertEqual(len(w), 1)
        self.assertIn("ghost", w[0])

    def test_notes_check_cli(self):
        make_docset(self.store_dir, "Py")
        self.write_notes("Py", "## asyncio.gather\nok\n")
        r = self.cli("notes", "Py", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.write_notes("Py", "## ghost\nok\n")
        r = self.cli("notes", "Py", "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ghost", r.stdout)
        r = self.cli("notes", "Missing", "--check")
        self.assertEqual(r.returncode, 5)


class FtsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)
        make_docset(self.store_dir, "Py", pages={
            "library/asyncio.html": DEFAULT_PAGES["library/asyncio.html"],
            "guide.html": DEFAULT_PAGES["guide.html"]})

    def cli(self, *args):
        return run_cli("--dir", self.store_dir, *args, env={"HOME": self.tmp},
                       cwd=self.tmp)

    def set_version(self, v):
        d = os.path.join(self.store_dir, ".dash-docset")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "installed.json"), "w") as f:
            json.dump({"Py": {"source": "kapeli", "version": v, "url": "u",
                              "installed": "2026-01-01"}}, f)

    def test_fts_finds_text_in_page(self):
        r = self.cli("fts", "b()", "-d", "Py")  # only in <pre>, with FTS syntax
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Py:page:library/asyncio.html#asyncio.gather\n", r.stdout)
        self.assertIn("gather", r.stdout)
        r = self.cli("show", "Py:page:library/asyncio.html#asyncio.gather")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("asyncio.gather", r.stdout)
        self.assertNotIn("Block for", r.stdout)  # trimmed to the matched section
        r = self.cli("fts", "Gather things", "-d", "Py", "--json")
        items = json.loads(r.stdout)
        self.assertTrue(items[0]["ref"].startswith("Py:page:guide.html"))
        self.assertEqual(sorted(items[0]), ["docset", "path", "ref", "snippet"])
        self.assertEqual(items[0]["path"], "guide.html")
        r = self.cli("fts", "zzzznothing", "-d", "Py")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "no matches for 'zzzznothing'")

    def test_snippet_phrases(self):
        self.assertEqual(docset._snippet_phrases(
            "...Also see \x02context\x03 \x02variable\x03. - A contextvars.\x02Context\x03 object..."),
            ["also see context variable", "context variable"])
        # literal brackets in the docs are not match marks
        self.assertEqual(docset._snippet_phrases(
            "get([default]) Return a value for the \x02context\x03 \x02variable\x03 for"),
            ["for the context variable for", "context variable for"])
        self.assertEqual(docset._snippet_phrases("no match marks"), [])

    def test_fts_cap_keeps_ref_with_snippet(self):
        r = self.cli("fts", "gather", "-d", "Py", "--max-lines", "2")
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("Py:page:"))
        self.assertTrue(lines[1].startswith("    "))
        self.assertTrue(lines[2].startswith("... "))
        self.assertIn("more hits cut", lines[2])

    def test_fts_first_build_says_so(self):
        r = self.cli("fts", "gather", "-d", "Py")
        self.assertIn("building the full-text index for Py", r.stderr)
        r = self.cli("fts", "gather", "-d", "Py")
        self.assertNotIn("building", r.stderr)

    def test_fts_index_layout_and_unreferenced_pages(self):
        with open(os.path.join(self.store_dir, "Py.docset", "Contents", "Resources",
                               "Documents", "orphan.html"), "w") as f:
            f.write("<p>orphanword</p>")
        r = self.cli("index-text", "Py")
        self.assertEqual(r.returncode, 0, r.stderr)
        db = os.path.join(self.store_dir, ".dash-docset", "fts", "Py.sqlite")
        con = sqlite3.connect(db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM pages").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM page_entries").fetchone()[0], 3)
        keys = {k for k, _ in con.execute("SELECT key, value FROM meta")}
        self.assertEqual(keys, {"docset_version", "built_at"})
        con.close()
        r = self.cli("fts", "orphanword", "-d", "Py")
        self.assertTrue(r.stdout.startswith("no matches"))

    def test_fts_rebuilds_stale(self):
        self.set_version("1")
        r = self.cli("fts", "Gather", "-d", "Py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("rebuilt", r.stderr)
        r = self.cli("fts", "Gather", "-d", "Py")
        self.assertNotIn("rebuilt", r.stderr)
        self.set_version("2")
        r = self.cli("fts", "Gather", "-d", "Py")
        self.assertIn("rebuilt index for Py", r.stderr)
        r = self.cli("fts", "Gather", "-d", "Py")
        self.assertNotIn("rebuilt", r.stderr)

    def test_fts_unavailable(self):
        import contextlib
        import io
        from unittest import mock
        for argv in (["fts", "x", "-d", "Py"], ["index-text", "Py"]):
            err = io.StringIO()
            with mock.patch.object(docset, "fts_available", return_value=False), \
                    contextlib.redirect_stderr(err):
                code = docset.main(["--dir", self.store_dir] + argv)
            self.assertEqual(code, 2)
            self.assertIn("FTS5", err.getvalue())

    def test_fts_scope_error(self):
        # 500+ entries make a store docset without a source full-size
        big = [("e%d" % i, "Function", "p.html") for i in range(500)]
        store2 = os.path.join(self.tmp, "s2")
        os.makedirs(store2)
        for i in range(5):
            make_docset(store2, "B%d" % i, entries=big, pages={"p.html": "<p>x</p>"})
        r = run_cli("--dir", store2, "fts", "x", env={"HOME": self.tmp}, cwd=self.tmp)
        self.assertEqual(r.returncode, 4)

    def test_parse_page_ref(self):
        self.assertEqual(docset.parse_page_ref("Py:page:library/a.html"),
                         ("Py", "library/a.html"))
        self.assertIsNone(docset.parse_page_ref("Py:12"))
        self.assertIsNone(docset.parse_page_ref("Py:page:"))

    def test_show_accepts_page_ref(self):
        r = self.cli("show", "Py:page:library/asyncio.html")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Run awaitables concurrently.", r.stdout)
        self.assertIn("Block for a number of seconds.", r.stdout)  # whole page
        r = self.cli("show", "Py:page:../../evil.html")
        self.assertEqual(r.returncode, 5)
        r = self.cli("show", "Py:page:nope.html")
        self.assertEqual(r.returncode, 5)

    def test_page_ref_for_page_without_entries(self):
        with open(os.path.join(self.store_dir, "Py.docset", "Contents", "Resources",
                               "Documents", "x.html"), "w") as f:
            f.write("<p>unlisted</p>")
        r = self.cli("show", "Py:page:x.html")
        self.assertIn("unlisted", r.stdout)


class Task7FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)

    def test_show_page_ref_with_literal_percent(self):
        make_docset(self.store_dir, "Pc", entries=[("x", "Guide", "50%x.html")],
                    pages={"50%x.html": "<p>percent page</p>"})
        r = run_cli("--dir", self.store_dir, "show", "Pc:page:50%x.html",
                    env={"HOME": self.tmp}, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("percent page", r.stdout)

    def test_fts_fetches_enough_hits_for_line_cap(self):
        import contextlib
        import io
        from unittest import mock
        make_docset(self.store_dir, "Pc", entries=[("x", "Guide", "a.html")],
                    pages={"a.html": "<p>word</p>"})
        seen = []

        def fake(store, docs, query, limit):
            seen.append(limit)
            return []
        for argv, want in ((["--max-lines", "10"], 6),
                           (["--max-lines", "10", "--json"], 10)):
            with mock.patch.object(docset, "fts_search", fake), \
                    contextlib.redirect_stdout(io.StringIO()):
                docset.main(["--dir", self.store_dir, "fts", "word", "-d", "Pc"] + argv)
            self.assertEqual(seen[-1], want)


# --- sources, install, update, remove --------------------------------------

import contextlib  # noqa: E402
import io  # noqa: E402
import tarfile  # noqa: E402
from unittest import mock  # noqa: E402

FEED_XML = ("<entry><version>%s</version>"
            "<url>http://one.example.com/feeds/Foo.tgz</url>"
            "<url>http://two.example.com/feeds/Foo.tgz</url>"
            "<other-versions><version><name>0.5</name></version>"
            "<url>http://old.example.com/Foo-0.5.tgz</url></other-versions></entry>")
USER_INDEX = {"docsets": {
    "Foo": {"name": "Foo", "archive": "Foo.tgz", "version": "9", "author": "x"},
    "Bar_Key": {"name": "Bar", "archive": "Bar.tgz", "version": "2.0"}}}


def make_tgz(path, docset_name="Foo", **kw):
    """Write a .tgz holding a fixture docset; return the path."""
    with tempfile.TemporaryDirectory() as d:
        make_docset(d, docset_name, **kw)
        with tarfile.open(path, "w:gz") as t:
            t.add(os.path.join(d, docset_name + ".docset"), arcname=docset_name + ".docset")
    return path


def bad_tgz(path, build):
    """A .tgz whose members `build(tarfile)` adds by hand."""
    with tarfile.open(path, "w:gz") as t:
        build(t)
    return path


def add_file(t, name, data=b"x"):
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    t.addfile(ti, io.BytesIO(data))


def add_special(t, name, typ, linkname=""):
    ti = tarfile.TarInfo(name)
    ti.type = typ
    ti.linkname = linkname
    t.addfile(ti)


class FakeNet:
    """Replaces fetch / download / head_last_modified; records the calls."""

    def __init__(self, test, pages=None, archives=None, heads=None):
        self.pages = dict(pages or {})
        self.archives = dict(archives or {})  # url -> local .tgz path
        self.heads = dict(heads or {})
        self.fetched, self.downloaded = [], []
        self.cond = []  # (url, etag, last_modified) of conditional requests
        for name, fn in (("fetch", self.fetch), ("download", self.download),
                         ("head_last_modified", self.head),
                         ("fetch_cond", self.fetch_cond)):
            p = mock.patch.object(docset, name, fn)
            p.start()
            test.addCleanup(p.stop)

    def fetch(self, url):
        self.fetched.append(url)
        if url not in self.pages:
            raise docset.FetchError("HTTP 404 for " + url, 404)
        v = self.pages[url]
        return v if isinstance(v, bytes) else v.encode()

    def fetch_cond(self, url, etag=None, last_modified=None):
        self.cond.append((url, etag, last_modified))
        body = self.fetch(url)
        tag = self.etags.get(url) if hasattr(self, "etags") else None
        if tag and etag == tag:
            return None, etag, last_modified
        return body, tag, None

    def download(self, url, dest):
        self.downloaded.append(url)
        if url not in self.archives:
            raise docset.FetchError("HTTP 503 for " + url, 503)
        with open(self.archives[url], "rb") as src, open(dest, "wb") as out:
            out.write(src.read())

    def head(self, url):
        return self.heads.get(url)


FEED_URL = docset.KAPELI_FEED_URL % "Foo"
MIRROR1 = "https://one.example.com/feeds/Foo.tgz"
MIRROR2 = "https://two.example.com/feeds/Foo.tgz"


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)
        self.store = docset.Store(self.store_dir, "flag", [], None)
        self.tgz = make_tgz(os.path.join(self.tmp, "Foo.tgz"))

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docset.main(["--dir", self.store_dir] + list(argv))
        return code, out.getvalue(), err.getvalue()

    def net(self, version="1.0", **kw):
        pages = {FEED_URL: FEED_XML % version}
        pages.update(kw.pop("pages", {}))
        archives = kw.pop("archives", {MIRROR2: self.tgz})
        return FakeNet(self, pages=pages, archives=archives, **kw)

    def test_parse_feeds(self):
        f = docset.parse_kapeli_xml(FEED_XML % "2.21.0", "Foo")
        self.assertEqual(f, docset.Feed("Foo", "kapeli", "2.21.0",
                                        [MIRROR1, MIRROR2]))
        feeds = docset.parse_index_json(USER_INDEX, "user", "https://h.example/build/")
        self.assertEqual([x.name for x in feeds], ["Foo", "Bar"])
        self.assertEqual(feeds[1], docset.Feed(
            "Bar", "user", "2.0", ["https://h.example/build/Bar_Key/Bar.tgz"]))
        with self.assertRaises(ValueError):
            docset.parse_kapeli_xml("<entry></entry>", "Foo")
        with self.assertRaises(ValueError):
            docset.parse_kapeli_xml("not xml", "Foo")

    def test_install_and_list(self):
        net = self.net()
        code, out, err = self.main("install", "kapeli:Foo")
        self.assertEqual(code, 0, err)
        self.assertEqual(net.downloaded, [MIRROR1, MIRROR2])  # first mirror failed
        self.assertTrue(os.path.isfile(os.path.join(
            self.store_dir, "Foo.docset", "Contents", "Resources", "docSet.dsidx")))
        inst = docset.load_installed(self.store)["Foo"]
        self.assertEqual((inst["source"], inst["version"], inst["url"]),
                         ("kapeli", "1.0", MIRROR2))
        self.assertRegex(inst["installed"], r"^\d{4}-\d\d-\d\d")
        code, out, err = self.main("list")
        self.assertIn("Foo  kapeli  1.0", out)
        self.assertEqual(os.listdir(os.path.join(self.store_dir, ".dash-docset")),
                         ["installed.json"])  # temp files cleaned up
        # an explicit prefix did not fetch the source lists (Ruling 8)
        self.assertEqual(net.fetched, [FEED_URL])
        code, out, err = self.main("search", "gather", "-d", "Foo")
        self.assertIn("asyncio.gather", out)

    def test_install_cheat_uses_last_modified(self):
        url = docset.CHEAT_URL % "Foo"
        net = FakeNet(self, archives={url: self.tgz},
                      heads={url: "Wed, 01 Jan 2025 00:00:00 GMT"})
        code, out, err = self.main("install", "cheat:Foo")
        self.assertEqual(code, 0, err)
        inst = docset.load_installed(self.store)["Foo"]
        self.assertEqual((inst["source"], inst["version"], inst["url"]),
                         ("cheat", "Wed, 01 Jan 2025 00:00:00 GMT", url))
        # only the cheat-sheet index was tried (it 404s here), no GitHub API
        self.assertEqual(net.fetched, [docset.CHEAT_INDEX_URL])

    def test_install_user_prefix(self):
        url = docset.USER_BASE_URL + "Foo/Foo.tgz"
        FakeNet(self, pages={docset.USER_INDEX_URL: json.dumps(USER_INDEX)},
                archives={url: self.tgz})
        code, out, err = self.main("install", "user:Foo")
        self.assertEqual(code, 0, err)
        self.assertEqual(docset.load_installed(self.store)["Foo"]["source"], "user")

    def test_install_not_found(self):
        self.net()
        code, out, err = self.main("install", "kapeli:Nope")
        self.assertEqual(code, 5)
        self.assertIn("not found", err)

    def test_install_ambiguous_needs_prefix(self):
        names = lambda a: json.dumps([{"name": n, "type": "file"} for n in a])
        self.net(pages={
            docset.KAPELI_LIST_URL: names(["Foo.xml", "Other.xml"]),
            docset.CHEAT_LIST_URL: names(["Foo.rb"]),
            docset.USER_INDEX_URL: json.dumps(USER_INDEX)})
        code, out, err = self.main("install", "Foo")
        self.assertEqual(code, 6)
        for p in ("kapeli:Foo", "user:Foo", "cheat:Foo"):
            self.assertIn(p, err)
        self.assertFalse(os.path.exists(os.path.join(self.store_dir, "Foo.docset")))
        code, out, err = self.main("install", "kapeli:Foo")
        self.assertEqual(code, 0, err)

    def test_install_unprefixed_unique(self):
        names = lambda a: json.dumps([{"name": n, "type": "file"} for n in a])
        self.net(pages={docset.KAPELI_LIST_URL: names(["Foo.xml"]),
                        docset.CHEAT_LIST_URL: names(["Zed.rb"]),
                        docset.USER_INDEX_URL: json.dumps(
                            {"docsets": {"Bar_Key": USER_INDEX["docsets"]["Bar_Key"]}})})
        code, out, err = self.main("install", "foo")  # case-insensitive
        self.assertEqual(code, 0, err)

    def test_all_mirrors_fail(self):
        self.net(archives={})
        code, out, err = self.main("install", "kapeli:Foo")
        self.assertEqual(code, 7)
        self.assertEqual(os.listdir(self.store_dir), [".dash-docset"] if
                         os.path.isdir(os.path.join(self.store_dir, ".dash-docset"))
                         else [])
        self.assertFalse(os.path.exists(
            os.path.join(self.store_dir, ".dash-docset", "installed.json")))

    def test_safe_extract_ok(self):
        dest = os.path.join(self.tmp, "out")
        os.makedirs(dest)
        path = docset.safe_extract(self.tgz, dest)
        self.assertEqual(path, os.path.join(dest, "Foo.docset"))
        self.assertTrue(os.path.isfile(os.path.join(path, "Contents", "Info.plist")))

    def test_safe_extract_rejects(self):
        def ok_member(t):
            add_file(t, "Foo.docset/Contents/Info.plist")
        cases = {
            "absolute": lambda t: (ok_member(t), add_file(t, "/tmp/evil.txt")),
            "dotdot": lambda t: (ok_member(t), add_file(t, "Foo.docset/../../evil.txt")),
            "symlink-out": lambda t: (ok_member(t), add_special(
                t, "Foo.docset/l", tarfile.SYMTYPE, "../../etc")),
            "symlink-abs": lambda t: (ok_member(t), add_special(
                t, "Foo.docset/l", tarfile.SYMTYPE, "/etc/passwd")),
            "hardlink-out": lambda t: (ok_member(t), add_special(
                t, "Foo.docset/h", tarfile.LNKTYPE, "../evil")),
            "device": lambda t: (ok_member(t), add_special(
                t, "Foo.docset/dev", tarfile.CHRTYPE)),
            "fifo": lambda t: (ok_member(t), add_special(
                t, "Foo.docset/ff", tarfile.FIFOTYPE)),
            "no-docset": lambda t: add_file(t, "readme.txt"),
            "two-docsets": lambda t: (add_file(t, "A.docset/x"), add_file(t, "B.docset/x")),
        }
        for label, build in cases.items():
            with self.subTest(label):
                tgz = bad_tgz(os.path.join(self.tmp, label + ".tgz"), build)
                dest = os.path.join(self.tmp, "d-" + label)
                os.makedirs(dest)
                with self.assertRaises(docset.ArchiveError):
                    docset.safe_extract(tgz, dest)
                # nothing escaped
                self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        plain = os.path.join(self.tmp, "plain.tgz")
        with open(plain, "wb") as f:
            f.write(b"this is not gzip at all")
        with self.assertRaises(docset.ArchiveError):
            docset.safe_extract(plain, self.tmp)

    def test_install_bad_archive_leaves_store_unchanged(self):
        bad = bad_tgz(os.path.join(self.tmp, "bad.tgz"),
                      lambda t: (add_file(t, "Foo.docset/Contents/Info.plist"),
                                 add_file(t, "../evil.txt")))
        self.net(archives={MIRROR1: bad})
        code, out, err = self.main("install", "kapeli:Foo")
        self.assertEqual(code, 7)
        self.assertFalse(os.path.exists(os.path.join(self.store_dir, "Foo.docset")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))
        self.assertFalse(os.path.exists(
            os.path.join(self.store_dir, ".dash-docset", "installed.json")))
        left = [n for n in os.listdir(os.path.join(self.store_dir, ".dash-docset"))]
        self.assertEqual(left, [])

    def test_update(self):
        self.net("1.0")
        self.assertEqual(self.main("install", "kapeli:Foo")[0], 0)
        code, out, err = self.main("update")
        self.assertEqual(code, 0, err)
        self.assertIn("Foo: up to date", out)
        # new version with changed content; notes heading now orphaned
        tgz2 = make_tgz(os.path.join(self.tmp, "Foo2.tgz"),
                        entries=[("brandnew", "Function", "guide.html")])
        self.net("2.0", archives={MIRROR1: tgz2})
        notes = docset.notes_path(self.store, "Foo")
        os.makedirs(os.path.dirname(notes))
        with open(notes, "w") as f:
            f.write("## brandnew\nkeep\n## asyncio.gather\ngone\n")
        code, out, err = self.main("update", "Foo")
        self.assertEqual(code, 0, err)
        self.assertIn("Foo: updated 1.0 -> 2.0", out)
        self.assertIn("asyncio.gather", out)  # orphan warning
        self.assertNotIn("brandnew' matches no", out)
        self.assertEqual(docset.load_installed(self.store)["Foo"]["version"], "2.0")
        code, out, _ = self.main("search", "brandnew", "-d", "Foo")
        self.assertIn("brandnew", out)
        self.assertEqual([n for n in os.listdir(self.store_dir)
                          if n.endswith(".docset")], ["Foo.docset"])
        self.assertTrue(os.path.exists(notes))

    def test_update_failure_keeps_old_docset(self):
        self.net("1.0")
        self.main("install", "kapeli:Foo")
        self.net("2.0", archives={})
        code, out, err = self.main("update")
        self.assertEqual(code, 7)
        self.assertEqual(docset.load_installed(self.store)["Foo"]["version"], "1.0")
        self.assertTrue(os.path.isdir(os.path.join(self.store_dir, "Foo.docset")))

    def test_update_and_remove_refuse_foreign(self):
        ro = os.path.join(self.tmp, "ro")
        os.makedirs(ro)
        make_docset(ro, "Alien")
        make_docset(self.store_dir, "Loose")  # in store, not in installed.json
        store_arg = ["--dir", self.store_dir]
        cfg = os.path.join(self.tmp, "proj")
        os.makedirs(cfg)
        with open(os.path.join(cfg, docset.PROJECT_FILE), "w") as f:
            json.dump({"store": self.store_dir, "read_from": [ro]}, f)
        old = os.getcwd()
        os.chdir(cfg)
        self.addCleanup(os.chdir, old)
        FakeNet(self)
        for cmd in ("update", "remove"):
            for name in ("Alien", "Loose"):
                with self.subTest(cmd=cmd, name=name):
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = docset.main([cmd, name])
                    self.assertEqual(code, 2, err.getvalue())
                    self.assertIn("not installed by docset.py", err.getvalue())
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = docset.main([cmd, "Nope"])
            self.assertEqual(code, 5)
        self.assertTrue(os.path.isdir(os.path.join(ro, "Alien.docset")))
        self.assertTrue(os.path.isdir(os.path.join(self.store_dir, "Loose.docset")))

    def test_remove_keeps_notes(self):
        self.net()
        self.main("install", "kapeli:Foo")
        notes = docset.notes_path(self.store, "Foo")
        os.makedirs(os.path.dirname(notes))
        with open(notes, "w") as f:
            f.write("## General\nhi\n")
        fts = docset.fts_path(self.store, "Foo")
        if docset.fts_available():
            self.assertEqual(self.main("index-text", "Foo")[0], 0)
            self.assertTrue(os.path.exists(fts))
        code, out, err = self.main("remove", "Foo")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(os.path.join(self.store_dir, "Foo.docset")))
        self.assertFalse(os.path.exists(fts))
        self.assertNotIn("Foo", docset.load_installed(self.store))
        self.assertTrue(os.path.exists(notes))
        self.assertIn("notes", out)

    def test_cheat_unknown_version_always_redownloads(self):
        url = docset.CHEAT_URL % "Foo"
        self.net(pages={}, archives={url: self.tgz}, heads={})
        self.assertEqual(self.main("install", "cheat:Foo")[0], 0)
        self.assertEqual(docset.load_installed(self.store)["Foo"]["version"],
                         docset.UNKNOWN_VERSION)
        net = self.net(pages={}, archives={url: self.tgz}, heads={})
        code, out, err = self.main("update", "Foo")
        self.assertEqual(code, 0, err)
        self.assertIn("version unknown", out)
        self.assertNotIn("up to date", out)
        self.assertEqual(net.downloaded, [url])

    def test_notes_rejects_path_names(self):
        self.net()
        self.main("install", "kapeli:Foo")
        for bad in ("../../x", "a/b", "a\\b", ".."):
            with self.subTest(bad=bad):
                code, out, err = self.main("notes", bad, "--path")
                self.assertEqual(code, 2, err)
        with self.assertRaises(docset.CLIError):
            docset.notes_path(self.store, "")

    def test_remove_symlinked_docset(self):
        target = os.path.join(self.tmp, "real")
        os.makedirs(target)
        make_docset(target, "Foo")
        os.symlink(os.path.join(target, "Foo.docset"),
                   os.path.join(self.store_dir, "Foo.docset"))
        docset.save_installed(self.store, {"Foo": {
            "source": "kapeli", "version": "1.0", "url": MIRROR1,
            "installed": "2026-11-14"}})
        code, out, err = self.main("remove", "Foo")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(os.path.join(self.store_dir, "Foo.docset")))
        self.assertTrue(os.path.isdir(os.path.join(target, "Foo.docset")))

    def test_remove_oserror_is_cli_error_7(self):
        self.net()
        self.main("install", "kapeli:Foo")
        with mock.patch.object(docset.shutil, "rmtree", side_effect=OSError("boom")):
            code, out, err = self.main("remove", "Foo")
        self.assertEqual(code, 7)
        self.assertIn("boom", err)

    def test_sources_cache_and_filter(self):
        names = lambda a: json.dumps([{"name": n, "type": "file"} for n in a])
        net = self.net(pages={
            docset.KAPELI_LIST_URL: names(["Python_3.xml", "Go.xml", "README.md"]),
            docset.CHEAT_LIST_URL: names(["Git.rb", "Python_Cheat.rb"]),
            docset.USER_INDEX_URL: json.dumps(USER_INDEX)})
        code, out, err = self.main("sources", "python")
        self.assertEqual(code, 0, err)
        self.assertIn("kapeli:Python_3", out)
        self.assertIn("cheat:Python_Cheat", out)
        self.assertNotIn("Go", out)
        self.assertNotIn("README", out)
        n = len(net.fetched)
        self.main("sources", "git")
        self.assertEqual(len(net.fetched), n)  # served from the cache
        self.main("sources", "git", "--refresh")
        again = net.fetched[n:]
        for url in (docset.KAPELI_LIST_URL, docset.CHEAT_LIST_URL, docset.USER_INDEX_URL):
            self.assertIn(url, again)
        # lists that failed (404) less than a day ago are not retried
        self.assertNotIn(docset.ZEAL_MANIFEST_URL, again)
        self.assertNotIn(docset.CHEAT_INDEX_URL, again)
        n = len(net.fetched)
        # a cache older than 7 days is refetched
        path = os.path.join(self.store_dir, ".dash-docset", "cache", "sources.json")
        with open(path) as f:
            data = json.load(f)
        for entry in data.values():
            entry["fetched"] -= 8 * 86400
        with open(path, "w") as f:
            json.dump(data, f)
        self.main("sources", "git")
        for url in (docset.KAPELI_LIST_URL, docset.CHEAT_LIST_URL, docset.USER_INDEX_URL):
            self.assertIn(url, net.fetched[n:])
        # a failing source falls back to the stale cache
        for entry in data.values():
            entry["fetched"] -= 8 * 86400
        with open(path, "w") as f:
            json.dump(data, f)
        net.pages.clear()
        code, out, err = self.main("sources", "git")
        self.assertEqual(code, 0)
        self.assertIn("cheat:Git", out)
        self.assertIn("warning", err)

    def test_install_invalid_docset_keeps_old(self):
        self.net("1.0")
        self.assertEqual(self.main("install", "kapeli:Foo")[0], 0)
        bad = {
            "no-index": lambda t: add_file(t, "Foo.docset/Contents/Info.plist"),
            "plain-file": lambda t: add_file(t, "Foo.docset"),
        }
        for label, build in bad.items():
            with self.subTest(label):
                tgz = bad_tgz(os.path.join(self.tmp, label + ".tgz"), build)
                self.net("2.0", archives={MIRROR1: tgz})
                code, out, err = self.main("install", "kapeli:Foo")
                self.assertEqual(code, 7, err)
                self.assertEqual(docset.load_installed(self.store)["Foo"]["version"], "1.0")
                self.assertEqual(self.main("search", "gather", "-d", "Foo")[0], 0)
                self.assertTrue(os.path.isfile(os.path.join(
                    self.store_dir, "Foo.docset", "Contents", "Resources", "docSet.dsidx")))

    def test_install_refuses_overwriting_other_docset(self):
        make_docset(self.store_dir, "Other")
        docset.save_installed(self.store, {"Other": {
            "source": "user", "version": "1", "url": "https://h.example/b/Other/O.tgz",
            "installed": "2026-01-01"}})
        other = make_tgz(os.path.join(self.tmp, "Other.tgz"), "Other",
                         entries=[("zzz", "Function", "guide.html")])
        self.net(archives={MIRROR1: other})
        code, out, err = self.main("install", "kapeli:Foo")
        self.assertEqual(code, 7)
        self.assertIn("overwrite", err)
        self.assertEqual(docset.load_installed(self.store)["Other"]["version"], "1")
        self.assertEqual(self.main("search", "zzz", "-d", "Other")[1].strip(),
                         "no matches for 'zzz'")

    def test_http_client_errors_become_fetch_errors(self):
        import http.client

        class Resp:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *a):
                raise http.client.IncompleteRead(b"ab")
        with mock.patch.object(docset.urllib.request, "urlopen", lambda *a, **k: Resp()):
            with self.assertRaises(docset.FetchError):
                docset.fetch("https://x.example/a")
            with self.assertRaises(docset.FetchError):
                docset.download("https://x.example/a", os.path.join(self.tmp, "d"))
        with mock.patch.object(docset.urllib.request, "urlopen",
                               side_effect=http.client.BadStatusLine("x")):
            with self.assertRaises(docset.FetchError):
                docset.fetch("https://x.example/a")
        # through install: exit 7, not a traceback
        FakeNet(self, pages={FEED_URL: FEED_XML % "1"})
        with mock.patch.object(docset, "download",
                               side_effect=docset.FetchError("IncompleteRead")):
            self.assertEqual(self.main("install", "kapeli:Foo")[0], 7)

    def test_unsafe_names_refused(self):
        net = FakeNet(self)
        for spec in ("kapeli:../x", "cheat:a/b", "kapeli:a/../b", "cheat:%2e%2e"):
            with self.subTest(spec):
                code, out, err = self.main("install", spec)
                self.assertEqual(code, 2, err)
        self.assertEqual(net.fetched, [])
        self.assertEqual(net.downloaded, [])

    def test_cheat_not_found_is_exit_5(self):
        def head404(url):
            raise docset.FetchError("HTTP 404 for " + url, 404)
        FakeNet(self)
        with mock.patch.object(docset, "head_last_modified", head404):
            code, out, err = self.main("install", "cheat:Nonexistent")
        self.assertEqual(code, 5)
        self.assertIn("not found", err)
        # a download that 404s on every mirror is also "not found"
        class N(FakeNet):
            def download(self, url, dest):
                raise docset.FetchError("HTTP 404", 404)
        N(self, heads={docset.CHEAT_URL % "Zed": "x"})
        code, out, err = self.main("install", "cheat:Zed")
        self.assertEqual(code, 5)
        self.assertIn("not found", err)

    def test_kapeli_404_suggests_unversioned_name(self):
        self.net()
        code, out, err = self.main("install", "kapeli:Foo_3")
        self.assertEqual(code, 5)
        self.assertIn("Did you mean kapeli:Foo?", err)
        self.assertIn("cheat:Foo_3", err)

    def test_unprefixed_not_found_hints_prefixes(self):
        FakeNet(self, pages={docset.USER_INDEX_URL: json.dumps(USER_INDEX)})
        code, out, err = self.main("install", "Zed")
        self.assertEqual(code, 5)
        self.assertIn("could not be loaded", err)
        self.assertIn("kapeli:Name", err)

    def test_sources_partial_list_says_so(self):
        FakeNet(self, pages={docset.USER_INDEX_URL: json.dumps(USER_INDEX)})
        code, out, err = self.main("sources")
        self.assertEqual(code, 7)
        self.assertIn("user:Foo", out)
        self.assertIn("incomplete list: the kapeli and cheat list", out)

    CHEAT_JSON = ('{"cheatsheets": {"Foo": {"version": "1.0.2", "name": "Foo Sheet",'
                  ' "aliases": ["shell",],},},}')  # trailing commas, as served

    def test_cheat_index_versions_and_aliases(self):
        url = docset.CHEAT_URL % "Foo"
        net = FakeNet(self, pages={docset.CHEAT_INDEX_URL: self.CHEAT_JSON},
                      archives={url: self.tgz})
        code, out, err = self.main("install", "cheat:foo")
        self.assertEqual(code, 0, err)
        self.assertEqual(docset.load_installed(self.store)["Foo"]["version"], "1.0.2")
        code, out, err = self.main("sources", "shell")
        self.assertIn("cheat:Foo  1.0.2", out)
        self.assertNotIn(docset.CHEAT_LIST_URL, net.fetched)  # index served it

    def test_zeal_name_and_pin(self):
        xml = ("<entry><version>3.15.0</version>"
               "<url>http://one.example.com/feeds/Foo.tgz</url>"
               "<other-versions><version><name>3.15.0</name></version>"
               "<version><name>3.12.6</name></version>"
               "<version><name>2.7.18</name></version></other-versions></entry>")
        old = docset.VERSIONED_PATH % ("Foo", "2.7.18", "Foo")
        pinned = docset.VERSIONED_PATH % ("Foo", "3.12.6", "Foo")
        manifest = {"Foo_2": {"title": "Foo 2", "source": "Foo", "versionPrefix": "2."}}
        FakeNet(self, pages={FEED_URL: xml,
                             docset.ZEAL_MANIFEST_URL: json.dumps(manifest)},
                archives={"https://one.example.com" + old: self.tgz,
                          "https://one.example.com" + pinned: self.tgz})
        code, out, err = self.main("install", "kapeli:Foo_2")
        self.assertEqual(code, 0, err)
        inst = docset.load_installed(self.store)["Foo"]
        self.assertEqual((inst["version"], inst["pin"]), ("2.7.18", "2."))
        code, out, err = self.main("install", "kapeli:Foo@3.12")
        self.assertEqual(code, 0, err)
        inst = docset.load_installed(self.store)["Foo"]
        self.assertEqual((inst["version"], inst["pin"]), ("3.12.6", "3.12"))
        code, out, err = self.main("update", "Foo")  # keeps the pin
        self.assertIn("up to date (3.12.6)", out)
        code, out, err = self.main("install", "kapeli:Foo@3.1")
        self.assertEqual(code, 5)  # 3.1 is not 3.12 or 3.15
        self.assertIn("no version 3.1", err)
        code, out, err = self.main("install", "cheat:Foo@1")
        self.assertEqual(code, 2)

    def test_zeal_catalog_last_resort_and_polite(self):
        catalog = json.dumps([
            {"name": "Foo", "title": "Foo", "sourceId": "com.kapeli.dash",
             "versions": ["1"], "icon": "x" * 100},
            {"name": "Sheet", "title": "Sheet", "sourceId": "com.kapeli.cheatsheet",
             "versions": ["2"]},
            {"name": "Bar_Key", "title": "Bar", "sourceId": "com.kapeli.contrib",
             "versions": ["3"], "archive": "Bar.tgz"}])
        net = FakeNet(self, pages={docset.ZEAL_CATALOG_URL: catalog})
        net.etags = {docset.ZEAL_CATALOG_URL: '"v1"'}
        code, out, err = self.main("sources")
        self.assertEqual(code, 0, err)
        for line in ("kapeli:Foo", "cheat:Sheet  2", "user:Bar  3"):
            self.assertIn(line, out)
        zeal = lambda: sum(u == docset.ZEAL_CATALOG_URL for u, _e, _l in net.cond)
        self.assertEqual(zeal(), 1)  # one request served all three sources
        body = os.path.join(self.store_dir, ".dash-docset", "cache", "zeal-catalog.body")
        with open(body) as f:
            self.assertNotIn("icon", f.read())  # cached without icons
        self.main("sources", "--refresh")
        self.assertEqual(zeal(), 1)  # --refresh does not re-check Zeal within the week
        meta_p = body[:-len(".body")] + ".meta.json"
        with open(meta_p) as f:
            meta = json.load(f)
        meta["checked"] -= 8 * 86400
        with open(meta_p, "w") as f:
            json.dump(meta, f)
        self.main("sources", "--refresh")
        self.assertEqual(net.cond[-1], (docset.ZEAL_CATALOG_URL, '"v1"', None))
        self.assertTrue(os.path.getsize(body) > 0)  # 304 kept the cached body

    def test_failed_fetch_not_retried_within_a_day(self):
        net = FakeNet(self)
        for _ in range(2):
            with self.assertRaises(docset.FetchError):
                docset.cached_get(self.store, "k", "https://x.example/a", 10)
        self.assertEqual(net.fetched, ["https://x.example/a"])

    def test_install_skips_same_version_and_foreign(self):
        net = self.net()
        self.assertEqual(self.main("install", "kapeli:Foo")[0], 0)
        n = len(net.downloaded)
        code, out, err = self.main("install", "kapeli:Foo")
        self.assertEqual(code, 0, err)
        self.assertIn("already installed", out)
        self.assertEqual(len(net.downloaded), n)  # no second download
        code, out, err = self.main("install", "--force", "kapeli:Foo")
        self.assertEqual(code, 0, err)
        self.assertGreater(len(net.downloaded), n)
        # a docset in a Zeal folder is used instead of downloading a copy
        zeal = os.path.join(self.tmp, "zeal")
        make_docset(zeal, "Bar")
        cfg = os.path.join(self.tmp, "cfg.json")
        with open(cfg, "w") as f:
            json.dump({"store": self.store_dir, "read_from": [zeal]}, f)
        bar_url = docset.KAPELI_FEED_URL % "Bar"
        net.pages[bar_url] = FEED_XML.replace("Foo", "Bar") % "1"
        with mock.patch.dict(os.environ, {"DASH_DOCSET_DIR": ""}):
            store = docset.Store(self.store_dir, "flag", [zeal], None)
            with self.assertRaises(docset.AlreadyAvailable) as cm:
                docset.install(store, "kapeli:Bar")
        self.assertIn("read-only from " + zeal, str(cm.exception))

    def test_sources_all_failing(self):
        FakeNet(self)
        code, out, err = self.main("sources")
        self.assertEqual(code, 7)


if __name__ == "__main__":
    unittest.main()


import shutil  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402


def make_tarix(docset_path):
    """Turn a fixture docset into Dash's tarix form: Documents/ packed into
    Contents/Resources/tarix.tgz (full zlib flush before each tar record)
    with tarixIndex.db mapping paths to '<block> <offset> <blocks>'."""
    name = os.path.basename(docset_path)
    res = os.path.join(docset_path, "Contents", "Resources")
    docs = os.path.join(res, "Documents")
    out = bytearray(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03")  # gzip header
    comp = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    crc, size, rows, block = 0, 0, [], 0
    for root, _dirs, files in sorted(os.walk(docs)):
        for fn in sorted(files):
            full = os.path.join(root, fn)
            arc = name + "/" + os.path.relpath(full, docset_path).replace(os.sep, "/")
            with open(full, "rb") as f:
                data = f.read()
            ti = tarfile.TarInfo(arc)
            ti.size = len(data)
            record = ti.tobuf(tarfile.GNU_FORMAT) + data + b"\0" * (-len(data) % 512)
            rows.append((arc, "%d %d %d" % (block, len(out), len(record) // 512)))
            out += comp.compress(record) + comp.flush(zlib.Z_FULL_FLUSH)
            crc, size, block = zlib.crc32(record, crc), size + len(record), block + len(record) // 512
    end = b"\0" * 1024
    out += comp.compress(end) + comp.flush()
    crc, size = zlib.crc32(end, crc), size + len(end)
    out += struct.pack("<II", crc & 0xffffffff, size & 0xffffffff)
    with open(os.path.join(res, "tarix.tgz"), "wb") as f:
        f.write(out)
    con = sqlite3.connect(os.path.join(res, "tarixIndex.db"))
    con.execute("CREATE TABLE tarindex(path TEXT PRIMARY KEY COLLATE NOCASE, hash TEXT)")
    con.executemany("INSERT INTO tarindex VALUES (?, ?)", rows)
    con.commit()
    con.close()
    shutil.rmtree(docs)


class TarixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)
        self.dash = os.path.join(self.tmp, "Dash", "DocSets", "Py")
        path = make_docset(self.dash, "Py")
        make_tarix(path)
        docset._TARIX.clear()

    def test_archive_is_a_valid_tgz(self):
        res = os.path.join(self.dash, "Py.docset", "Contents", "Resources")
        with tarfile.open(os.path.join(res, "tarix.tgz")) as t:
            self.assertTrue(any(n.endswith("asyncio.html") for n in t.getnames()))

    def test_show_and_fts_read_from_archive(self):
        ds = docset._make_docset(os.path.join(self.dash, "Py.docset"), True, None, None)
        text = "\n".join(b.text for b in docset.read_page_blocks(ds, "library/asyncio.html"))
        self.assertIn("asyncio.gather", text)
        with self.assertRaises(docset.CLIError) as cm:
            docset.read_page_blocks(ds, "library/missing.html")
        self.assertEqual(cm.exception.code, 5)
        store = docset.Store(self.store_dir, "flag", [os.path.dirname(self.dash)], None)
        if docset.fts_available():
            self.assertGreater(docset.build_fts(store, ds), 0)
            hits = docset.fts_search(store, [ds], "gather", 5)
            self.assertTrue(any(h["ref"].startswith("Py:page:library/asyncio.html") for h in hits), hits)

    def test_bad_index_entry_is_exit_7(self):
        res = os.path.join(self.dash, "Py.docset", "Contents", "Resources")
        con = sqlite3.connect(os.path.join(res, "tarixIndex.db"))
        con.execute("UPDATE tarindex SET hash = '0 5 999999999'")
        con.commit()
        con.close()
        docset._TARIX.clear()
        ds = docset._make_docset(os.path.join(self.dash, "Py.docset"), True, None, None)
        with self.assertRaises(docset.CLIError) as cm:
            docset.read_page_blocks(ds, "library/asyncio.html")
        self.assertEqual(cm.exception.code, 7)
