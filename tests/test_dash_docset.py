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


if __name__ == "__main__":
    unittest.main()
