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

    def test_stub_exits_2(self):
        r = run_cli("sources")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not implemented", r.stderr)

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

    def test_unset_exits_3_and_lists_discovered(self):
        dasht = os.path.join(self.env["XDG_DATA_HOME"], "dasht", "docsets")
        os.makedirs(dasht)
        r = run_cli("where", env=self.cli_env(), cwd=self.sub)
        self.assertEqual(r.returncode, 0, r.stderr)  # where itself reports unset
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
        names = [l.split("  ")[2] for l in r.stdout.splitlines()]
        self.assertEqual(names, ["Sleep", "sleep", "sleep_long", "xsleepx", "s_l_e_e_p"])
        first = r.stdout.splitlines()[0].split("  ")
        self.assertEqual(first[1], "Guide")
        self.assertEqual(first[3], "(Beta)")
        self.assertRegex(first[0], r"^Beta:\d+$")
        self.assertTrue(r.stdout.splitlines()[1].startswith("Alpha:2  "))

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
        self.assertIn("general tip", r.stdout)
        self.assertEqual(r.stdout.count("general tip"), 1)
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


if __name__ == "__main__":
    unittest.main()
