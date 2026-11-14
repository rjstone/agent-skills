"""Offline tests for skills/dash-docset/scripts/docset.py.

No network: docsets are built by make_docset() in temp dirs. Run from the
repo root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import plistlib
import sqlite3
import subprocess
import sys
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


def run_cli(*args, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True,
                          text=True, env=full_env)


class SkeletonTests(unittest.TestCase):
    def test_help_lists_subcommands(self):
        r = run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in SUBCOMMANDS:
            self.assertIn(name, r.stdout)

    def test_stub_exits_2(self):
        r = run_cli("where")
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


if __name__ == "__main__":
    unittest.main()
