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


def run_cli(*args, env=None, cwd=None):
    full_env = dict(os.environ)
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


if __name__ == "__main__":
    unittest.main()
