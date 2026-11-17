"""Offline tests for skills/docshelf. No network: docvols are built by
make_devdocs() in temp dirs. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import atexit
import contextlib
import io
import json
import os
import plistlib
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import types
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
import shelf_backends  # noqa: E402
import shelf_cli  # noqa: E402
import shelf_dash  # noqa: E402
from shelf_core import CLIError  # noqa: E402
import shelf_core  # noqa: E402
import shelf_devdocs  # noqa: E402
import shelf_lookup  # noqa: E402
import shelf_notes  # noqa: E402
import shelf_render  # noqa: E402

_EMPTY = tempfile.mkdtemp(prefix="docshelf-empty-")
atexit.register(shutil.rmtree, _EMPTY, ignore_errors=True)

# Variables removed for every test: they would leak the real cache or notes,
# or point discovery at real docset folders or a real Zeal/Dash install. Every
# XDG_* variable goes too. HOME, USERPROFILE and PATH are replaced by an empty
# folder instead, and DOCSHELF_NO_SYSTEM_APPS=1 (a test hook of shelf_dash)
# skips the fixed app paths (/Applications, /var/lib/flatpak) and the registry.
LEAKY_ENV = ("DOCSHELF_CACHE_DIR", "DOCSHELF_NOTES_DIR", "APPDATA", "LOCALAPPDATA",
             "OLDPWD", "ProgramFiles", "ProgramFiles(x86)", "DASHT_DOCSETS_DIR",
             "DOCSHELF_DOCSET_DIRS")
ISOLATED_ENV = {"PATH": _EMPTY, "HOME": _EMPTY, "USERPROFILE": _EMPTY,
                "DOCSHELF_NO_SYSTEM_APPS": "1"}


def clean_env():
    """os.environ without the LEAKY_ENV and XDG_* variables, plus
    ISOLATED_ENV: a real Zeal or Dash install is never found."""
    env = {k: v for k, v in os.environ.items()
           if k not in LEAKY_ENV and not k.startswith("XDG_")}
    env.update(ISOLATED_ENV)
    return env


_MODULE_PATCHES: list = []


def setUpModule():
    """In-process tests read os.environ and shelf_dash's system locations:
    same isolation as clean_env, plus no fixed app paths and no registry,
    undone afterwards (other test modules need PATH)."""
    _MODULE_PATCHES[:] = [
        mock.patch.dict(os.environ),
        mock.patch.object(shelf_dash, "SYSTEM_APP_PATHS", ()),
        mock.patch.object(shelf_dash, "_zeal_registry_path", lambda: None)]
    for p in _MODULE_PATCHES:
        p.start()
    for k in [k for k in os.environ if k in LEAKY_ENV or k.startswith("XDG_")]:
        del os.environ[k]
    os.environ.update(ISOLATED_ENV)


def tearDownModule():
    for p in reversed(_MODULE_PATCHES):
        p.stop()


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
    the manifest row to <cache>/devdocs/docs.json; return the docvol folder.

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


def make_docset(root: str, name: str, entries: List[Tuple[str, str, str]],
                pages: Dict[str, str], form: str = "searchIndex",
                plist_name: Optional[str] = None,
                meta_version: Optional[str] = None, wal: bool = False) -> str:
    """Write <root>/<name>.docset/Contents/{Info.plist, Resources/docSet.dsidx,
    Resources/Documents/...} and return the .docset folder.

    entries are (name, type, path); form "ztoken" writes the Core Data tables
    with the anchor in ZANCHOR; wal=True leaves the rows in docSet.dsidx-wal."""
    ds = os.path.join(root, name + ".docset")
    res = os.path.join(ds, "Contents", "Resources")
    os.makedirs(res, exist_ok=True)
    if plist_name is not None:
        with open(os.path.join(ds, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleName": plist_name}, f)
    if meta_version is not None:
        with open(os.path.join(ds, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"version": meta_version}, f)
    for page, html in pages.items():
        full = os.path.join(res, "Documents", *page.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(html)
    db = os.path.join(res, "docSet.dsidx")
    work = tempfile.mkdtemp() if wal else None
    target = os.path.join(work, "docSet.dsidx") if wal else db
    con = sqlite3.connect(target)
    try:
        if wal:
            con.execute("PRAGMA journal_mode=wal")
            con.execute("PRAGMA wal_autocheckpoint=0")
        if form == "ztoken":
            con.executescript(
                "CREATE TABLE ZTOKEN (Z_PK INTEGER PRIMARY KEY, ZTOKENNAME TEXT,"
                " ZTOKENTYPE INTEGER, ZMETAINFORMATION INTEGER);"
                "CREATE TABLE ZTOKENTYPE (Z_PK INTEGER PRIMARY KEY, ZTYPENAME TEXT);"
                "CREATE TABLE ZTOKENMETAINFORMATION (Z_PK INTEGER PRIMARY KEY,"
                " ZFILE INTEGER, ZANCHOR TEXT);"
                "CREATE TABLE ZFILEPATH (Z_PK INTEGER PRIMARY KEY, ZPATH TEXT);")
            types: Dict[str, int] = {}
            for i, (n, t, path) in enumerate(entries, 1):
                if t not in types:
                    types[t] = len(types) + 1
                    con.execute("INSERT INTO ZTOKENTYPE VALUES (?, ?)", (types[t], t))
                file_part, _, anchor = path.partition("#")
                con.execute("INSERT INTO ZFILEPATH VALUES (?, ?)", (i, file_part))
                con.execute("INSERT INTO ZTOKENMETAINFORMATION VALUES (?, ?, ?)",
                            (i, i, anchor or None))
                con.execute("INSERT INTO ZTOKEN VALUES (?, ?, ?, ?)",
                            (i, n, types[t], i))
        else:
            con.execute("CREATE TABLE searchIndex (id INTEGER PRIMARY KEY, "
                        "name TEXT, type TEXT, path TEXT)")
            con.executemany("INSERT INTO searchIndex (name, type, path) "
                            "VALUES (?, ?, ?)", entries)
        con.commit()
        if wal:  # copy while the writer is open: the rows are still in -wal
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(target + suffix):
                    shutil.copyfile(target + suffix, db + suffix)
    finally:
        con.close()
        if work:
            shutil.rmtree(work, ignore_errors=True)
    return ds


def make_tarix(docset: str, files: Dict[str, bytes]) -> None:
    """Move the docset's Documents/ files into Contents/Resources/tarix.tgz
    (a zlib full flush before every tar record) and write tarixIndex.db."""
    import tarfile
    import zlib
    res = os.path.join(docset, "Contents", "Resources")
    shutil.rmtree(os.path.join(res, "Documents"), ignore_errors=True)
    name = os.path.basename(docset)
    comp = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    out = bytearray(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03")  # gzip header
    rows = []
    for rel, data in files.items():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:", format=tarfile.USTAR_FORMAT) as tar:
            info = tarfile.TarInfo("%s/Contents/Resources/Documents/%s" % (name, rel))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        record = buf.getvalue()[:-1024]  # drop the end-of-archive blocks
        out += comp.flush(zlib.Z_FULL_FLUSH)
        rows.append(("%s/Contents/Resources/Documents/%s" % (name, rel),
                     "%d %d %d" % (0, len(out), len(record) // 512)))
        out += comp.compress(record)
    out += comp.flush(zlib.Z_FINISH)
    with open(os.path.join(res, "tarix.tgz"), "wb") as f:
        f.write(bytes(out))
    con = sqlite3.connect(os.path.join(res, "tarixIndex.db"))
    try:
        con.execute("CREATE TABLE tarindex (path TEXT PRIMARY KEY COLLATE NOCASE, hash TEXT)")
        con.executemany("INSERT INTO tarindex VALUES (?, ?)", rows)
        con.commit()
    finally:
        con.close()


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
        self.assertTrue(r.stdout.startswith("docshelf %s" % shelf_core.VERSION), r.stdout)
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
            json.dump({"docvols": ["python~3.12"]}, f)
        r = run_cli("where", env=self.env(OLDPWD=proj), cwd=SKILL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("project: %s" % os.path.join(proj, ".docshelf.json"), r.stdout)
        self.assertIn("OLDPWD", r.stderr)

    def test_bad_project_docvols(self):
        with open(os.path.join(self.work, ".docshelf.json"), "w") as f:
            json.dump({"docvols": "x"}, f)
        r = run_cli("where", env=self.env(), cwd=self.work)
        self.assertEqual(r.returncode, 2)
        self.assertIn(".docshelf.json", r.stderr)

    def test_load_config_reads_docvols(self):
        with open(os.path.join(self.work, ".docshelf.json"), "w") as f:
            json.dump({"docvols": ["a", "b~1"]}, f)
        cfg = shelf_core.load_config(self.work, self.env())
        self.assertEqual(cfg.project_docvols, ["a", "b~1"])
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

    def project(self, folder, docvols=("x",)):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, ".docshelf.json"), "w") as f:
            json.dump({"docvols": list(docvols)}, f)

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
        d = shelf_devdocs.installed_docvols(self.cfg())[0]
        self.assertEqual(d.page_html("guide"), "<p>hi</p>")
        db = os.path.join(folder, "db.json")
        with open(db, "w", encoding="utf-8") as f:
            json.dump({"guide": "<p>new text</p>"}, f, ensure_ascii=False)
        os.utime(db, (1800000000, 1800000000))
        d2 = shelf_devdocs.installed_docvols(self.cfg())[0]
        self.assertEqual(d2.page_html("guide"), "<p>new text</p>")
        self.assertEqual(d.page_html("guide"), "<p>new text</p>")  # same object too

    def test_works_without_derived_dir(self):
        folder = self.make()
        d = shelf_devdocs.installed_docvols(self.cfg())[0]
        d.page_html("guide")
        derived = os.path.join(folder, ".docshelf")
        shutil.rmtree(derived)
        d2 = shelf_devdocs.installed_docvols(self.cfg())[0]
        self.assertEqual(d2.page_html("guide"), "<p>hi</p>")
        self.assertTrue(os.path.isfile(os.path.join(derived, "pages.json")))

    def test_entries_and_resolve(self):
        self.make(entries=[("Guide", "Guide", "guide"),
                           ("Sec", "Guide", "guide#sec")],
                  pages={"guide": "<p>x</p>"})
        d = shelf_devdocs.installed_docvols(self.cfg())[0]
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
        names = [d.name for d in shelf_devdocs.installed_docvols(self.cfg())]
        self.assertEqual(names, ["alpha", "zed"])

    def test_list(self):
        r = run_cli("list", env=self.env, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         "no docvols installed (install NAME; sources QUERY finds names)")
        self.make("vite", name="Vite", release="5")
        big = {"p%d" % i: "x" for i in range(500)}
        self.make("big~2", name="Big", release="2",
                  entries=[("E%d" % i, "T", k) for i, k in enumerate(big)],
                  pages=big)
        r = run_cli("list", env=self.env, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "big~2  Big  2  500 entries  full  devdocs",
            "vite  Vite  5  1 entries  small  devdocs"])

    def test_pick_family_ambiguous(self):
        self.make("python~3.13", name="Python", release="3.13.8", alias="py")
        self.make("python~3.14", name="Python", release="3.14.8", alias="py")
        self.make("vite")
        self.make("node~24_lts", name="Node.js", release="24.14.0")
        self.make("ruby~3.4", name="Ruby", release="3.4.1", version="3.4 x")
        ds = shelf_devdocs.installed_docvols(self.cfg())
        for q in ("python", "py"):
            with self.assertRaises(shelf_core.CLIError) as cm:
                shelf_core.pick_docvol(ds, q)
            self.assertEqual(cm.exception.code, 2)
            self.assertIn("python~3.13", str(cm.exception))
            self.assertIn("python~3.14", str(cm.exception))
        self.assertEqual(shelf_core.pick_docvol(ds, "Python 3.14").name, "python~3.14")
        self.assertEqual(shelf_core.pick_docvol(ds, "VITE").name, "vite")
        self.assertEqual(shelf_core.pick_docvol(ds, "Vite").title, "Vite")
        self.assertEqual(shelf_core.pick_docvol(ds, "Node.js 24 LTS").name, "node~24_lts")
        self.assertEqual(shelf_core.pick_docvol(ds, "Ruby 3.4 x").name, "ruby~3.4")
        with self.assertRaises(shelf_core.CLIError) as cm:
            shelf_core.pick_docvol(ds, "nope")
        self.assertEqual(cm.exception.code, 5)
        with self.assertRaises(shelf_core.ScopeError):
            shelf_core.select_docvols(self.cfg(), ds, ["nope"], False)
        self.assertEqual(len(shelf_core.select_docvols(self.cfg(), ds, [], False)), 5)


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


def sec(html, anchor):
    return shelf_render.section_lines(shelf_render.html_to_text(html), anchor)[0]


class AnchorTests(unittest.TestCase):
    def test_dash_anchor_before_heading(self):
        html = ('<a name="//apple_ref/cpp/Function/foo" class="dashAnchor"></a>'
                '<h3>foo()</h3><p>does foo</p><h3>bar()</h3><p>bar</p>')
        self.assertEqual(sec(html, "//apple_ref/cpp/Function/foo"),
                         ["### foo()", "does foo"])

    def test_doc2dash_anchor_before_dt(self):
        html = ('<dl><a name="//apple_ref/cpp/Function/os.path.join" class="dashAnchor"></a>'
                '<dt id="os.path.join">os.path.join(a, *p)</dt><dd>Join paths.</dd>'
                '<dt id="os.path.split">os.path.split(p)</dt><dd>Split.</dd></dl>')
        self.assertEqual(sec(html, "//apple_ref/cpp/Function/os.path.join"),
                         ["os.path.join(a, *p)", "Join paths."])

    def test_stacked_anchors_all_attach(self):
        html = ('<a name="//dash_ref_1/Section/Intro/0" class="dashAnchor"></a>'
                '<a name="intro"></a><h2 id="top">Intro</h2><p>x</p><h2>Next</h2>')
        for a in ("//dash_ref_1/Section/Intro/0", "intro", "top"):
            self.assertEqual(sec(html, a), ["## Intro", "x"])

    def test_encoded_once_and_twice(self):
        html = ('<a name="//dash_ref_1/Section/Intro/0" class="dashAnchor"></a>'
                '<h2>Intro</h2><p>x</p><h2>Next</h2>')
        for a in ("%2F%2Fdash_ref_1%2FSection%2FIntro%2F0",
                  "%252F%252Fdash_ref_1%252FSection%252FIntro%252F0"):
            self.assertEqual(sec(html, a), ["## Intro", "x"])

    def test_space_in_anchor(self):
        html = '<h2 id="read csv">read csv</h2><p>x</p><h2>Next</h2>'
        self.assertEqual(sec(html, "read%20csv"), ["## read csv", "x"])

    def test_name_on_any_tag(self):
        html = '<h2 name="setup">Setup</h2><p>x</p><h2>Other</h2>'
        self.assertEqual(sec(html, "setup"), ["## Setup", "x"])

    def test_details_is_one_section(self):
        html = ('<p>Before.</p><details id="opt-a"><summary>Option a</summary>'
                '<p>About a.</p><ul><li>one</li></ul></details>'
                '<p>After.</p><h2>Next</h2>')
        self.assertEqual(sec(html, "opt-a"), ["Option a", "About a.", "- one"])

    def test_first_block_in_page_order_wins(self):
        html = ('<a name="dup" class="dashAnchor"></a><h3>First</h3><p>1</p>'
                '<h3 id="dup">Second</h3><p>2</p>')
        self.assertEqual(sec(html, "dup"), ["### First", "1"])

    def test_unknown_anchor_whole_page_with_note(self):
        lines = sec('<h2>A</h2><p>x</p>', "//apple_ref/cpp/Function/nope")
        self.assertTrue(lines[0].startswith("note: anchor not found"))
        self.assertIn("## A", lines)

    def test_summary_id_promotes_to_details(self):
        # rustdoc: the id sits on <summary>; the section is the whole <details>
        html = ('<p>B</p><details><summary id="m"><code>set_len</code></summary>'
                '<p>About.</p></details><h2>N</h2>')
        self.assertEqual(sec(html, "m"), ["set_len", "About."])

    def test_empty_marker_inside_dt_and_li(self):
        # texinfo + Dash markers: an empty <a name> inside the <dt> / <li>
        dl = ('<dl><dt><a name="//apple_ref/Builtin/mapfile" class="dashAnchor"></a>'
              'mapfile</dt><dd>Read.</dd><dt><a name="//apple_ref/Builtin/n" '
              'class="dashAnchor"></a>next</dt><dd>n</dd></dl>')
        self.assertEqual(sec(dl, "//apple_ref/Builtin/mapfile"), ["mapfile", "Read."])
        ul = '<ul><li><a name="x"></a>item x</li><li><a name="y"></a>item y</li></ul>'
        self.assertEqual(sec(ul, "x"), ["- item x"])

    def test_doxygen_anchor_inside_heading(self):
        html = '<h2><a class="anchor" id="grp"></a> Title</h2><p>body</p><h2>Other</h2>'
        self.assertEqual(sec(html, "grp"), ["## Title", "body"])

    def test_show_docset_apple_ref_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            html = ('<a name="//apple_ref/cpp/Function/foo" class="dashAnchor"></a>'
                    '<h3>foo()</h3><p>does foo</p><h3>bar()</h3><p>bar</p>')
            make_docset(tmp, "Foo", [("foo", "Function",
                                      "api.html#//apple_ref/cpp/Function/foo")],
                        {"api.html": html})
            env = {"HOME": tmp, "USERPROFILE": tmp, "DOCSHELF_DOCSET_DIRS": tmp,
                   "DOCSHELF_CACHE_DIR": os.path.join(tmp, "cache"),
                   "DOCSHELF_NOTES_DIR": os.path.join(tmp, "notes")}
            s = run_cli("search", "foo", "--json", env=env, cwd=tmp)
            self.assertEqual(s.returncode, 0, s.stderr)
            ref = json.loads(s.stdout)[0]["ref"]
            r = run_cli("show", ref, env=env, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("### foo()", r.stdout)
            self.assertIn("does foo", r.stdout)
            self.assertNotIn("bar", r.stdout)


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
            "no matches for 'enemy arrow' (entry names and page headings"), r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 1)

    def test_docvol_name_is_case_insensitive(self):
        self.add("alpha", [("date_sub", "Function", "date#sub")])
        r = self.cli("search", "date_sub", "-d", "ALPHA")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha:date#sub", r.stdout)
        r = self.cli("search", "date_sub", project={"docvols": ["Alpha"]})
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

    def test_search_ranks_across_docvols(self):
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
        self.assertTrue(r.stdout.startswith(
            "no matches for 'qqq' (entry names and page headings"), r.stdout)
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

    def test_unknown_docvol_exits_4(self):
        self.add("alpha")
        r = self.cli("search", "x", "-d", "Nope")
        self.assertEqual(r.returncode, 4)
        self.assertIn("Nope", r.stderr)

    def test_scope_names_beat_project(self):
        self.add("alpha", [("thing", "Function", "a")])
        self.add("beta", [("thing", "Function", "b")])
        r = self.cli("search", "thing", "-d", "beta",
                     project={"docvols": ["alpha"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("beta:", r.stdout)
        self.assertNotIn("alpha:", r.stdout)

    def test_scope_project_list(self):
        for n in "abcdef":
            self.add("doc" + n, [("thing", "Function", "a")])
        r = self.cli("search", "thing", project={"docvols": ["docb", "docc"]})
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
        for hint in ("-d", "docvols", ".docshelf.json", "--all"):
            self.assertIn(hint, r.stderr)
        r = self.cli("search", "thing", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 5)

    def test_scope_small_docvols_dont_count(self):
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
        self.assertEqual(set(data[0]), {"ref", "docvol", "type", "name", "rank"})
        self.assertEqual((data[0]["docvol"], data[0]["rank"], data[1]["rank"]),
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

    def test_docvol_name_in_ref_is_case_insensitive(self):
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
                self.assertIn("<docvol>:<path>[#anchor]", r.stderr)

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


class ShowOffsetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        body = "".join("<p>row %d</p>" % i for i in range(399))
        make_devdocs(self.cache, "l", name="L", release="1",
                     entries=[("sec", "Section", "p#s")],
                     pages={"p": "<h2 id='s'>Sec</h2>" + body})

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def full(self):
        return self.cli("show", "l:p#s", "--full", "--no-notes").stdout.splitlines()

    def test_offset_skips_lines(self):
        full = self.full()
        self.assertEqual(len(full), 400)
        r = self.cli("show", "l:p#s", "--offset", "150", "--no-notes")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out[0], full[150])
        self.assertEqual(out[149], full[299])

    def test_cut_line_names_next_offset(self):
        r = self.cli("show", "l:p#s", "--no-notes")
        self.assertEqual(r.stdout.splitlines()[-1],
                         "... 250 more lines; --offset 150 continues (or --full)")
        r = self.cli("show", "l:p#s", "--offset", "150", "--no-notes")
        self.assertEqual(r.stdout.splitlines()[-1],
                         "... 100 more lines; --offset 300 continues (or --full)")

    def test_offset_with_full_prints_rest(self):
        full = self.full()
        r = self.cli("show", "l:p#s", "--offset", "150", "--full", "--no-notes")
        self.assertEqual(r.stdout.splitlines(), full[150:])

    def test_offset_past_end(self):
        for n in ("400", "999"):
            r = self.cli("show", "l:p#s", "--offset", n, "--no-notes")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(),
                             "nothing at --offset %s: the output has 400 lines" % n)

    def test_offset_with_grep(self):
        r = self.cli("show", "l:p#s", "--grep", "row 1", "--full", "--no-notes")
        hits = r.stdout.splitlines()[:-1]
        self.assertGreater(len(hits), 30)
        r = self.cli("show", "l:p#s", "--grep", "row 1", "--offset", "5",
                     "--max-lines", "3", "--no-notes")
        out = r.stdout.splitlines()
        self.assertEqual(out[:3], hits[5:8])
        self.assertEqual(out[3], "... %d more lines; --offset 8 continues (or --full)"
                         % (len(hits) - 8))
        self.assertTrue(out[4].startswith("(all "))

    def test_offset_zero_ok_negative_rejected(self):
        self.assertEqual(self.cli("show", "l:p#s", "--offset", "0").returncode, 0)
        self.assertEqual(self.cli("show", "l:p#s", "--offset", "-1").returncode, 2)

    def titled_with_notes(self):
        body = "".join("<p>row %d</p>" % i for i in range(20))
        make_devdocs(self.cache, "t", name="T", release="1",
                     entries=[("sec", "Section", "p#s")],
                     pages={"p": "<h1>Big Page</h1><h2 id='s'>Sec</h2>" + body})
        notes = os.path.join(self.tmp, "notes")
        os.makedirs(notes, exist_ok=True)
        with open(os.path.join(notes, "t.md"), "w", encoding="utf-8") as f:
            f.write("General note here.\n")
        r = self.cli("show", "t:p#s", "--full")
        self.assertIn("(page: Big Page)", r.stdout)
        self.assertIn("General note here.", r.stdout)
        return len([l for l in r.stdout.splitlines()
                    if not l.startswith(("(page:", "---", "## General", "General note"))])

    def test_offset_past_end_prints_only_message(self):
        total = self.titled_with_notes()
        r = self.cli("show", "t:p#s", "--offset", "999")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout,
                         "nothing at --offset 999: the output has %d lines\n" % total)

    def test_offset_continuation_skips_notes(self):
        self.titled_with_notes()
        r = self.cli("show", "t:p#s", "--offset", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("General note here.", r.stdout)
        self.assertNotIn("--- notes", r.stdout)
        r = self.cli("show", "t:p#s", "--offset", "0")
        self.assertIn("General note here.", r.stdout)


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
        return shelf_core.pick_docvol(shelf_devdocs.installed_docvols(self.cfg),
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
        self.assertIn("## General: shown by every show of this docvol", lines)
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
        self.assertEqual(sorted(items[0]), ["docvol", "page", "ref", "snippet"])
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
        self.assertEqual(shelf_render.unquote_all("Guide/Out%2520of%2520Memory"),
                         "Guide/Out of Memory")
        self.assertEqual(shelf_render.unquote_all("plain"), "plain")

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
        self.assertEqual(len(lines), 2)  # the cut line does not fit the cap

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
        self.assertEqual(keys, {"docvol_version", "built_at"})
        con.close()
        r = self.cli("fts", "gather", "-d", "py")  # already built: silent
        self.assertEqual(r.stderr, "")
        r = self.cli("index-text", "nope")
        self.assertEqual(r.returncode, 5)

    def test_fts_rebuilds_when_docvol_rewritten(self):
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


class FtsIdentifierTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        make_devdocs(
            self.cache, "py", name="Py", release="1",
            entries=[("A", "Guide", "pa"), ("B", "Guide", "pb"),
                     ("C", "Guide", "pc"), ("D", "Guide", "pd")],
            pages={"pa": "<h1>A</h1><p>Pass return_exceptions to collect errors.</p>",
                   "pb": "<h1>B</h1><p>Return the value. Many words later, "
                         "exceptions are raised.</p>",
                   "pc": "<h1>C</h1><p>Use getElementById to find nodes.</p>",
                   "pd": "<h1>D</h1><p>Call os.path.join for paths.</p>"})

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def db(self):
        return os.path.join(self.cache, "devdocs", "py", ".docshelf", "fts.sqlite")

    def test_identifier_with_underscore_ranks_first(self):
        r = self.cli("fts", "return_exceptions", "-d", "py", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)[0]["page"], "pa")

    def test_camelcase_identifier(self):
        for q in ("getElementById", "getelementbyid", "get element by id"):
            r = self.cli("fts", q, "-d", "py", "--json")
            self.assertEqual([h["page"] for h in json.loads(r.stdout)][:1],
                             ["pc"], q)

    def test_dotted_identifier(self):
        for q in ("os.path.join", "ospathjoin"):
            r = self.cli("fts", q, "-d", "py", "--json")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(r.stdout)[0]["page"], "pd", q)

    def test_punctuation_only_query(self):
        r = self.cli("fts", "-", "()", "-d", "py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "no searchable words in '- ()'")

    def test_any_word_retry_note(self):
        r = self.cli("fts", "collect", "nodes", "-d", "py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0],
                         "note: no page has all the words; showing pages "
                         "with any of them")
        self.assertIn("py:pa", r.stdout)
        r = self.cli("fts", "collect", "nodes", "-d", "py", "--json")
        self.assertIn("note: no page has all", r.stderr)
        self.assertEqual(len(json.loads(r.stdout)), 2)

    def test_any_word_retry_note_counts_toward_max_lines(self):
        for n in (1, 2):
            r = self.cli("fts", "collect", "nodes", "-d", "py", "--max-lines", str(n))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lines = r.stdout.splitlines()
            self.assertTrue(1 <= len(lines) <= n, (n, r.stdout))
            self.assertTrue(lines[0].startswith("note: no page has all"), r.stdout)
        self.assertTrue(lines[1].startswith("py:"), r.stdout)

    def test_no_searchable_words_builds_no_index(self):
        r = self.cli("fts", "-", "()", "-d", "py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.db()))

    def test_no_note_when_all_words_match(self):
        r = self.cli("fts", "collect", "errors", "-d", "py")
        self.assertNotIn("note:", r.stdout)

    def test_plain_word_prefers_prose(self):
        make_devdocs(
            self.cache, "el", name="El", release="1",
            entries=[("PA", "Guide", "pa"), ("PB", "Guide", "pb")],
            pages={"pa": "<h1>PA</h1><p>getElementById setElementValue ElementTree "
                         "getElementById setElementValue ElementTree</p>",
                   "pb": "<h1>PB</h1><p>An element is a node. Each element has "
                         "a name; element names matter.</p>"})
        r = self.cli("fts", "element", "-d", "el", "--json")
        self.assertEqual(json.loads(r.stdout)[0]["page"], "pb", r.stdout)

    def test_ids_deduplicated(self):
        ids = shelf_lookup.page_identifiers("self.x " * 50 + "getFoo getFoo")
        self.assertEqual(ids.split(), ["selfx", "getfoo", "get", "foo"])

    def test_existing_index_rebuilt(self):
        self.cli("fts", "getElementById", "-d", "py")
        con = sqlite3.connect(self.db())
        con.execute("UPDATE meta SET value=? WHERE key='docvol_version'",
                    ("old|fts5",))
        con.commit()
        con.close()
        r = self.cli("fts", "getElementById", "-d", "py")
        self.assertIn("rebuilt index", r.stderr)
        self.assertIn("py:pc", r.stdout)


class FtsMaxLinesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        make_devdocs(self.cache, "many", name="Many", release="1",
                     entries=[("p%d" % i, "Guide", "p%d" % i) for i in range(8)],
                     pages={"p%d" % i: "<h1>P%d</h1><p>zebra zebra %d</p>" % (i, i)
                            for i in range(8)})

    def test_max_lines_never_exceeded(self):
        for n in (1, 2, 3):
            r = run_cli("fts", "zebra", "-d", "many", "--max-lines", str(n),
                        env=self.env, cwd=self.tmp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lines = r.stdout.splitlines()
            self.assertTrue(1 <= len(lines) <= n, (n, r.stdout))
            self.assertTrue(lines[0].startswith("many:"), r.stdout)


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


def remote_docvol(slug, entries, pages):
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
            pages.update(remote_docvol(r["slug"], self.entries, self.pages))
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

    def test_failed_update_keeps_old_docvol(self):
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
        self.assertIn("cannot reach devdocs.io", err)
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


TOP_HELP_EXPECTED = "docshelf " + shelf_core.VERSION + """\
: look up DevDocs documentation offline (stdlib only).
This is the command reference; `<command> --help` adds only the options
listed at the end. REF = <docvol>:<path>[#anchor], as search and fts print
them; <docvol> is the name `list` prints. A Dash/Zeal docset's REFs read
<Name>:<id> (an entry) and <Name>:page:<path>[#anchor] (a page).
A docvol is a DevDocs documentation or a read-only Dash/Zeal docset on disk,
plus docshelf's own metadata, indexes and notes. -d NAME takes a docvol or
a family name (all its docvols, with a note).

Look up (usual order):
  search QUERY... [-d NAME]      entries whose names contain all the words,
                                 and headings inside pages when no entry
                                 name is an exact match; one REF per hit,
                                 best first
  show REF                       that entry's section (max 150 lines) plus
                                 your notes for it
  show REF --grep=TEXT           only lines containing TEXT, with their
                                 heading, table header row, and a matching
                                 term's definition (repeatable; plain text,
                                 not a pattern, case-insensitive)
  toc REF                        the page's headings, indented, each with
                                 its REF (to show one section)
  fts QUERY... [-d NAME]         words inside pages, 5 best hits with REFs;
                                 include the function name: fts read_csv skip
  types [-d NAME]                each docvol's entry types with counts, most
                                 frequent first (the names `search --type` takes)

Notes (format: references/notes.md in the skill folder):
  notes DOCVOL --path            the notes file to edit
  notes DOCVOL --check           after editing: which REFs show each section,
                                 then "ok"
  notes DOCVOL --set HEADING --text TEXT   write a section (--delete HEADING
                                 removes it), then the --check report

Get and manage docvols (references/getting-docvols.md):
  list                           docvols, versions, source (devdocs, zeal,
                                 dash) and "also as" redundancy flags
  sources QUERY...               documentations DevDocs offers, with sizes;
                                 docsets Dash or Zeal could download
  install [NAME...] [--force]    download one (NAME without a version = the
                                 newest; no NAME = the project's docvols
                                 list); refuses documentation already on
                                 disk as a docset unless --force; update
                                 [NAME...]; remove NAME (DevDocs docvols
                                 only: Dash or Zeal manages docsets)
  where                          cache, notes folder, project file, docset
                                 folders and Dash/Zeal apps found
  index-text DOCVOL              build the fts index now

Only if you need these, see `<command> --help`:
  search     --type --all --max-lines --json
  show       --full --max-lines --offset --no-notes
  toc        --max-lines
  fts        --all --max-lines --json
  types      --all
  sources    --refresh
  install    --force
Global: --version, --mcp (run as a stdio MCP server; references/mcp.md).
Exit codes: 0 ok; 1 notes --check found problems; 2 usage error, ambiguous
  name or no FTS5; 4 search scope too wide (use -d, a project list or --all)
  or unknown -d name; 5 not found (docvol, page or entry); 7 network
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

    def test_skill_md_mentions_no_dash_docvol(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Credits", text)
        self.assertIn("https://devdocs.io", text)


    def test_no_dash_docvol_text_in_any_skill_file(self):
        for dirpath, dirs, files in os.walk(SKILL):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                for bad in ("dash-docvol", "docvol.py", ".dash-docvol"):
                    self.assertNotIn(bad, text, path)


class TocTests(unittest.TestCase):
    PAGE = ("<h1 id='t'>T</h1><h2 id='a'>A</h2><h3 id='b'>B</h3>"
            "<h2 id='c'>C</h2>")
    WANT = ["(page: T)", "T  lib:p#t", "  A  lib:p#a", "    B  lib:p#b",
            "  C  lib:p#c"]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        make_devdocs(self.cache, "lib", name="Lib", release="1",
                     entries=[("fb", "Function", "p#b")],
                     pages={"p": self.PAGE})

    def toc(self, *args):
        r = run_cli("toc", *args, env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_toc_lists_headings_with_refs(self):
        self.assertEqual(self.toc("lib:p").splitlines(), self.WANT)

    def test_toc_from_entry_ref_lists_whole_page(self):
        self.assertEqual(self.toc("lib:p#b").splitlines(), self.WANT)

    def test_toc_anchorless_heading_uses_enclosing_anchor(self):
        make_devdocs(self.cache, "lib2", name="Lib2", release="1",
                     entries=[("x", "Function", "q")],
                     pages={"q": "<h1 id='t'>T</h1><h2>A</h2>"})
        self.assertEqual(self.toc("lib2:q").splitlines(),
                         ["(page: T)", "T  lib2:q#t", "  A  lib2:q#t"])

    def test_toc_max_lines_caps(self):
        lines = self.toc("lib:p", "--max-lines", "2").splitlines()
        self.assertEqual(lines[:3], self.WANT[:3])
        self.assertEqual(len(lines), 4)
        self.assertIn("more lines cut", lines[3])

    def test_toc_docset_refs(self):
        make_docset(self.tmp, "Dset", [("fb", "Function", "p.html")],
                    {"p.html": self.PAGE})
        env = dict(self.env, DOCSHELF_DOCSET_DIRS=self.tmp,
                   XDG_DATA_HOME=os.path.join(self.tmp, "data"),
                   PATH=os.path.join(self.tmp, "path"))
        r = run_cli("toc", "Dset:page:p.html", env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "(page: T)", "T  Dset:page:p.html#t", "  A  Dset:page:p.html#a",
            "    B  Dset:page:p.html#b", "  C  Dset:page:p.html#c"])

    def test_toc_over_mcp(self):
        mcp = McpTests("test_initialize_and_list")
        mcp.setUp()
        self.addCleanup(mcp.doCleanups)
        make_devdocs(mcp.cache, "lib", name="Lib", release="1",
                     entries=[("fb", "Function", "p#b")],
                     pages={"p": self.PAGE})
        r = mcp.call("toc", {"ref": "lib:p"})
        self.assertFalse(r["isError"], r)
        cli = run_cli("toc", "lib:p", env=mcp.env, cwd=mcp.tmp)
        self.assertEqual(r["content"][0]["text"], cli.stdout)
        self.assertEqual(cli.stdout.splitlines(), self.WANT)


class TypesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def add(self, slug, types):
        entries = [("e%d" % i, t, "p") for i, t in enumerate(types)]
        make_devdocs(self.cache, slug, name=slug.capitalize(), release="1",
                     entries=entries, pages={"p": "<p>t</p>"})

    def test_types_counts_sorted(self):
        self.add("lib", ["Function"] * 3 + ["Class"] + ["Method"] * 3)
        r = run_cli("types", "-d", "lib", env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "lib", "  3  Function", "  3  Method", "  1  Class"])

    def test_types_empty_type_is_no_type(self):
        self.add("lib", ["", "", "Class"])
        r = run_cli("types", "-d", "lib", env=self.env, cwd=self.tmp)
        self.assertEqual(r.stdout.splitlines(),
                         ["lib", "  2  (no type)", "  1  Class"])

    def test_types_two_docvols(self):
        self.add("alpha", ["Function", "Function", "Class"])
        self.add("beta", ["Macro"])
        r = run_cli("types", "-d", "alpha", "-d", "beta", env=self.env,
                    cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            "alpha", "  2  Function", "  1  Class", "beta", "  1  Macro"])
        r = run_cli("types", "--all", env=self.env, cwd=self.tmp)
        self.assertEqual(r.stdout.splitlines()[0], "alpha")

    def test_types_docset(self):
        make_docset(self.tmp, "Dset", [("a", "Function", "p.html"),
                                       ("b", "Function", "p.html"),
                                       ("c", "Class", "p.html")],
                    {"p.html": "<p>t</p>"})
        env = dict(self.env, DOCSHELF_DOCSET_DIRS=self.tmp,
                   XDG_DATA_HOME=os.path.join(self.tmp, "data"),
                   PATH=os.path.join(self.tmp, "path"))
        r = run_cli("types", "-d", "Dset", env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(),
                         ["Dset", "  2  Function", "  1  Class"])

    def test_types_over_mcp(self):
        mcp = McpTests("test_initialize_and_list")
        mcp.setUp()
        self.addCleanup(mcp.doCleanups)
        make_devdocs(mcp.cache, "lib", name="Lib", release="1",
                     entries=[("a", "Function", "p"), ("b", "Class", "p"),
                              ("c", "Function", "p")],
                     pages={"p": "<p>t</p>"})
        r = mcp.call("types", {"docvols": ["lib"]})
        self.assertFalse(r["isError"], r)
        cli = run_cli("types", "-d", "lib", env=mcp.env, cwd=mcp.tmp)
        self.assertEqual(r["content"][0]["text"], cli.stdout)
        self.assertEqual(cli.stdout.splitlines(),
                         ["lib", "  2  Function", "  1  Class"])


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
                                           "remove", "search", "show", "sources",
                                           "toc", "types"])
        q = by_name["search"]["inputSchema"]
        self.assertEqual(q["properties"]["query"]["type"], "array")
        self.assertEqual(q["properties"]["query"]["items"], {"type": "string"})
        self.assertIn("query", q["required"])
        self.assertEqual(q["properties"]["max_lines"]["type"], "integer")
        self.assertEqual(q["properties"]["all"]["type"], "boolean")
        self.assertEqual(q["properties"]["docvols"]["type"], "array")
        self.assertEqual(sorted(by_name["notes"]["inputSchema"]["properties"]),
                         ["check", "delete", "docvol", "set", "text"])

    def test_set_over_mcp(self):
        r = self.call("notes", {"docvol": "alpha", "set": "frobnicate",
                                "text": "Prefer frob2."})
        self.assertFalse(r.get("isError"), r)
        path = os.path.join(self.tmp, "notes", "alpha.md")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "## frobnicate\nPrefer frob2.\n")
        r = self.call("notes", {"docvol": "alpha", "delete": "nope"})
        self.assertTrue(r["isError"])

    def test_notes_path_with_set_refused_over_mcp(self):
        r = self.call("notes", {"docvol": "alpha", "path": True, "set": "x",
                                "text": "y"})
        self.assertTrue(r["isError"], r)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "notes", "alpha.md")))

    def test_not_installed_docvol_names_the_install_tool(self):
        add_listed_only(self.cache, "duckdb", "DuckDB")
        r = self.call("search", {"query": ["x"], "docvols": ["duckdb"]})
        self.assertTrue(r["isError"])
        self.assertIn("docvol 'duckdb' is not installed; DevDocs has it: run "
                      "the `install` tool with names [\"duckdb\"]",
                      r["content"][0]["text"])

    def test_search_matches_cli(self):
        r = self.call("search", {"query": ["frobnicate"], "docvols": ["alpha"]})
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
        r = self.call("notes", {"docvol": "alpha"})
        self.assertFalse(r["isError"], r)
        self.assertIn("notes file not present", r["content"][0]["text"])
        os.makedirs(os.path.join(self.tmp, "notes"))
        with open(os.path.join(self.tmp, "notes", "alpha.md"), "w",
                  encoding="utf-8") as f:
            f.write("## frobnicate\nUse it twice.\n")
        r = self.call("notes", {"docvol": "alpha"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(r["content"][0]["text"], "## frobnicate\nUse it twice.\n")
        r = self.call("notes", {"docvol": "alpha", "check": True})
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
            data.update(remote_docvol(r["slug"], entries,
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
            with mock.patch.object(shelf_devdocs, "installed_docvols",
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
        a = shelf_devdocs.installed_docvols(self.cfg())[0]
        b = shelf_devdocs.installed_docvols(self.cfg())[0]
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


class NotesWriteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.notes = os.path.join(self.tmp, "notes")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": self.notes}
        make_devdocs(self.cache, "python~3.13", name="Python", release="1",
                     entries=[("asyncio.gather", "Function", "a#asyncio.gather"),
                              ("Guide", "Guide", "guide")],
                     pages={"a": "<h2 id='asyncio.gather'>asyncio.gather</h2><p>x</p>",
                            "guide": "<h1>Guide</h1><p>Text.</p>"})
        self.file = os.path.join(self.notes, "python.md")

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def put(self, text):
        os.makedirs(self.notes, exist_ok=True)
        with open(self.file, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self):
        with open(self.file, encoding="utf-8", newline="") as f:
            return f.read()

    def test_set_adds_section_creates_file(self):
        r = self.cli("notes", "python", "--set", "asyncio.gather", "--text", "Use TaskGroup.")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), "## asyncio.gather\nUse TaskGroup.\n")
        self.assertIn("wrote " + self.file, r.stdout)
        self.assertIn("ok", r.stdout)
        r = self.cli("notes", "python", "--set", "Guide", "--text", "a\nb")
        self.assertEqual(self.read(), "## asyncio.gather\nUse TaskGroup.\n\n## Guide\na\nb\n")

    def test_set_replaces_existing_section(self):
        src = "intro\n\n## a\nold\nmore\n\n## b\nkeep\n\n## c\nkeep2\n"
        self.put(src)
        r = self.cli("notes", "python", "--set", "b", "--text", "new")
        self.assertEqual(r.returncode, 0, r.stderr)  # a --check warning does not fail the write
        self.assertIn("warning:", r.stdout)
        self.assertEqual(self.read(),
                         "intro\n\n## a\nold\nmore\n\n## b\nnew\n\n## c\nkeep2\n")
        self.cli("notes", "python", "--set", "General", "--text", "hi")
        self.assertEqual(self.read(),
                         "hi\n\n## a\nold\nmore\n\n## b\nnew\n\n## c\nkeep2\n")

    def test_set_general_creates_at_top(self):
        self.put("## a\nx\n")
        self.cli("notes", "python", "--set", "General", "--text", "g")
        self.assertEqual(self.read(), "## General\ng\n\n## a\nx\n")
        self.cli("notes", "python", "--set", "General", "--text", "g2")
        self.assertEqual(self.read(), "## General\ng2\n\n## a\nx\n")

    def test_set_typed_heading(self):
        self.put("## open\nplain\n\n## open (Function)\nfn\n")
        self.cli("notes", "python", "--set", "open (Function)", "--text", "fn2")
        self.assertEqual(self.read(), "## open\nplain\n\n## open (Function)\nfn2\n")
        self.cli("notes", "python", "--set", "open (Class)", "--text", "c")
        self.assertTrue(self.read().endswith("\n\n## open (Class)\nc\n"))

    def test_delete_section(self):
        self.put("## a\n1\n\n## b\n2\n\n## c\n3\n")
        r = self.cli("notes", "python", "--delete", "b")
        self.assertEqual(r.returncode, 0, r.stderr)  # a --check warning does not fail the write
        self.assertIn("warning:", r.stdout)
        self.assertEqual(self.read(), "## a\n1\n\n## c\n3\n")
        self.cli("notes", "python", "--delete", "c")
        self.assertEqual(self.read(), "## a\n1\n")

    def test_delete_missing_exit_5(self):
        self.put("## a\n1\n")
        r = self.cli("notes", "python", "--delete", "zzz")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.read(), "## a\n1\n")

    def test_set_text_with_heading_line_refused(self):
        self.put("## a\n1\n")
        r = self.cli("notes", "python", "--set", "b", "--text", "x\n## c\ny")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.read(), "## a\n1\n")

    def test_flag_combinations_exit_2(self):
        for args in (["--set", "a"], ["--text", "a"],
                     ["--set", "a", "--text", "b", "--delete", "a"]):
            self.assertEqual(self.cli("notes", "python", *args).returncode, 2, args)

    def test_set_over_limit_refused_file_unchanged(self):
        self.put("## a\n1\n")
        r = self.cli("notes", "python", "--set", "b",
                     "--text", "\n".join("l%d" % i for i in range(150)))
        self.assertEqual(r.returncode, 2)
        self.assertIn("limit", r.stderr)
        self.assertEqual(self.read(), "## a\n1\n")

    def test_invalid_utf8_refused_file_unchanged(self):
        os.makedirs(self.notes, exist_ok=True)
        raw = b"## a\ncaf\xe9\n\n## b\nkeep\n"
        with open(self.file, "wb") as f:
            f.write(raw)
        for args in (["--set", "b", "--text", "new"], ["--delete", "b"]):
            r = self.cli("notes", "python", *args)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("not valid UTF-8", r.stderr)
            self.assertIn("not written", r.stderr)
            with open(self.file, "rb") as f:
                self.assertEqual(f.read(), raw)

    def test_unreadable_notes_path_refused(self):
        os.makedirs(self.file)  # a directory where the notes file should be
        marker = os.path.join(self.file, "keep")
        with open(marker, "w") as f:
            f.write("x")
        r = self.cli("notes", "python", "--set", "a", "--text", "b")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("cannot read", r.stderr)
        self.assertIn("not written", r.stderr)
        self.assertTrue(os.path.isdir(self.file))
        self.assertTrue(os.path.exists(marker))

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix",
                         "symlinks need POSIX here")
    def test_symlinked_notes_file_stays_symlink(self):
        real_dir = os.path.join(self.tmp, "real")
        os.makedirs(real_dir)
        real = os.path.join(real_dir, "python.md")
        with open(real, "w", encoding="utf-8") as f:
            f.write("## a\n1\n")
        os.makedirs(self.notes, exist_ok=True)
        os.symlink(real, self.file)
        r = self.cli("notes", "python", "--set", "b", "--text", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.islink(self.file))
        with open(real, encoding="utf-8") as f:
            self.assertEqual(f.read(), "## a\n1\n\n## b\n2\n")
        self.assertEqual([n for n in os.listdir(self.notes)], ["python.md"])

    @unittest.skipUnless(os.name == "posix", "file modes are POSIX")
    def test_write_keeps_file_mode(self):
        self.put("## a\n1\n")
        os.chmod(self.file, 0o644)
        self.cli("notes", "python", "--set", "b", "--text", "2")
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o644)
        os.chmod(self.file, 0o640)
        self.cli("notes", "python", "--set", "b", "--text", "3")
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o640)

    @unittest.skipUnless(os.name == "posix", "file modes are POSIX")
    def test_new_file_mode_follows_umask(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        self.cli("notes", "python", "--set", "a", "--text", "1")
        self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o644)

    def test_path_with_write_flags_exit_2(self):
        self.put("## a\n1\n")
        for args in (["--set", "b", "--text", "x"], ["--delete", "a"], ["--text", "x"]):
            r = self.cli("notes", "python", "--path", *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("--path", r.stderr)
            self.assertEqual(self.read(), "## a\n1\n")

    def test_set_heading_with_hashes_stripped(self):
        self.cli("notes", "python", "--set", "## foo", "--text", "x")
        self.assertEqual(self.read(), "## foo\nx\n")
        self.cli("notes", "python", "--set", "  ##  foo ", "--text", "y")
        self.assertEqual(self.read(), "## foo\ny\n")
        r = self.cli("notes", "python", "--delete", "## foo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), "")

    def test_crlf_text_and_file_stay_lf(self):
        self.put("## a\n1\n")
        self.cli("notes", "python", "--set", "b", "--text", "x\r\ny")
        self.assertEqual(self.read(), "## a\n1\n\n## b\nx\ny\n")


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

    def test_old_format_headings_cache_is_rebuilt(self):
        ds = shelf_devdocs.DevDocsDocvol(self.folder)
        os.makedirs(ds.data_dir(), exist_ok=True)
        with open(os.path.join(ds.data_dir(), "headings.json"), "w") as f:
            json.dump({"stamp": ds.stamp(),
                       "headings": {"sql/utility": [["bogus", None]]}}, f)
        self.write_notes("## count_if\nNon-zero counts as true.\n")
        r = self.cli("notes", "duckdb", "--check")
        self.assertEqual(r.stdout.splitlines()[-1], "ok", r.stdout)

    def test_check_says_how_many_pages_it_could_not_read(self):
        self.write_notes("## count_if\nNon-zero counts as true.\n")
        real = shelf_devdocs.DevDocsDocvol.page_html

        def page_html(ds, page):
            if page == "sql/other":
                raise ValueError("broken page")
            return real(ds, page)
        out = io.StringIO()
        with mock.patch.object(shelf_devdocs.DevDocsDocvol, "page_html", page_html), \
                mock.patch.dict(os.environ, self.env), \
                contextlib.redirect_stdout(out):
            code = shelf_cli.main(["notes", "duckdb", "--check"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("note: 1 page could not be read; its headings are not "
                      "checked", out.getvalue().splitlines())

    def test_grep_rewrite_stops_at_double_dash(self):
        self.assertEqual(
            shelf_cli._join_grep_values(
                ["show", "R", "--grep", "a", "--", "--grep", "b"]),
            ["show", "R", "--grep=a", "--", "--grep", "b"])

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
        self.assertNotIn("matches no entry in the docvol", r.stdout)

    def test_headings_cache_rebuilt_when_db_changes(self):
        self.write_notes("## count_if\nx\n## sum\ny\n")
        r = self.cli("notes", "duckdb", "--check")
        self.assertIn("warning: section 'sum' matches no entry or page heading",
                      r.stdout)
        cache = os.path.join(self.folder, shelf_devdocs.DERIVED, "headings.json")
        self.assertTrue(os.path.isfile(cache))
        with open(cache, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["stamp"], "%s|headings%d" % (
                shelf_devdocs.DevDocsDocvol(self.folder).stamp(),
                shelf_notes.HEADINGS_FORMAT))
        with open(os.path.join(self.folder, "db.json"), encoding="utf-8") as f:
            pages = json.load(f)
        pages["sql/other"] = self.OTHER + "<h3 id='sumx'>sum(x)</h3><p>Adds.</p>"
        with open(os.path.join(self.folder, "db.json"), "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        r = self.cli("notes", "duckdb", "--check")
        self.assertIn("## sum: shown by show duckdb:sql/other#sumx", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_heading_without_id_uses_enclosing_anchor(self):
        shelf_ds = shelf_devdocs.DevDocsDocvol(self.folder)
        blocks = shelf_render.html_to_text(
            "<h2 id='a'>A</h2><h4>no_id(x)</h4><h2>Bare</h2>")
        self.assertEqual(shelf_notes.heading_refs(blocks),
                         [("A", "a"), ("no_id(x)", "a"), ("Bare", None)])
        self.assertTrue(shelf_ds.pages())


class SearchHeadingTests(unittest.TestCase):
    """search falls back to headings inside pages when no entry name matches
    (DuckDB indexes whole sections, so function names are only headings)."""
    UTIL, OTHER = NotesPageHeadingTests.UTIL, NotesPageHeadingTests.OTHER

    def setUp(self):
        NotesPageHeadingTests.setUp(self)

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def test_entry_miss_lists_matching_page_headings(self):
        r = self.cli("search", "count_if", "-d", "duckdb")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertIn("headings inside pages", out[0])
        self.assertIn("duckdb:sql/utility#count_ifx  (heading)  count_if(x)", out)
        self.assertNotIn("typeof", r.stdout)

    def test_entry_hit_skips_headings(self):
        r = self.cli("search", "misc", "-d", "duckdb")
        self.assertIn("duckdb:sql/other#misc  Section  Misc", r.stdout.splitlines())
        self.assertNotIn("(heading)", r.stdout)

    def test_type_filter_skips_headings(self):
        r = self.cli("search", "count_if", "-d", "duckdb", "--type", "Section")
        self.assertNotIn("(heading)", r.stdout)
        self.assertTrue(r.stdout.startswith(
            "no matches for 'count_if' (entry names only"), r.stdout)

    def add_beta(self):
        page = ("<h2 id='regex'>Regular Expressions</h2>"
                "<h3 id='using-rx'>Using rx_extract</h3><p>u</p>"
                "<h4 id='rx_extracts'>rx_extract(s)</h4><p>e</p>"
                "<h4 id='rx_extract_alls'>rx_extract_all(s)</h4><p>a</p>")
        make_devdocs(self.cache, "beta", name="Beta", release="1",
                     entries=[("Using rx_extract", "Section", "re#using-rx"),
                              ("Regular Expressions", "Section", "re#regex")],
                     pages={"re": page})

    def test_substring_entry_hit_still_adds_exact_headings_first(self):
        self.add_beta()
        r = self.cli("search", "rx_extract", "-d", "beta")
        self.assertEqual(r.stdout.splitlines(), [
            "beta:re#rx_extracts  (heading)  rx_extract(s)",
            "beta:re#using-rx  Section  Using rx_extract"])

    def test_entry_hit_leaves_out_prefix_headings(self):
        self.add_beta()
        r = self.cli("search", "regular", "-d", "beta")
        self.assertEqual(r.stdout.splitlines(),
                         ["beta:re#regex  Section  Regular Expressions"])

    def test_json_marks_heading_hits(self):
        r = self.cli("search", "typeof", "-d", "duckdb", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [
            {"ref": "duckdb:sql/utility#typeofx", "docvol": "duckdb",
             "type": "(heading)", "name": "typeof(x)", "rank": 0}])


class ClosedPipeTests(unittest.TestCase):
    """Output piped into a reader that stops early (`show REF | head`) ends
    quietly, without an error message."""

    def test_closed_stdout_is_quiet(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = os.path.join(tmp.name, "cache")
        body = "".join("<p>line %d %s</p>" % (i, "x" * 60) for i in range(20000))
        make_devdocs(cache, "big", name="Big", release="1",
                     entries=[("big", "Guide", "big")], pages={"big": body})
        env = clean_env()
        env.update({"DOCSHELF_CACHE_DIR": cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(tmp.name, "notes")})
        p = subprocess.Popen([sys.executable, SCRIPT, "show", "big:big",
                              "--max-lines", "100000"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        p.stdout.readline()
        p.stdout.close()  # what `head -1` does
        err = p.stderr.read().decode("utf-8", "replace")
        p.stderr.close()
        p.wait(timeout=60)
        self.assertNotIn("BrokenPipe", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(err, "")


class AttributionTests(unittest.TestCase):
    """DevDocs ends every page with a licence notice and the upstream URL
    (div._attribution); docshelf leaves it out of what it renders."""
    ATTR = ('<div class="_attribution">\n  <p class="_attribution-p">\n'
            '    &copy; 2006&ndash;2020 Team<br>Licensed under the Zlib License.<br>\n'
            '    <a href="https://example.org/wiki/f" class="_attribution-link">'
            'https://example.org/wiki/f</a>\n  </p>\n</div>\n')

    def setUp(self):
        SearchTests.setUp(self)

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def add(self, page):
        make_devdocs(self.cache, "lib", name="Lib", release="1",
                     entries=[("f", "Function", "f")], pages={"f": page})

    def test_show_leaves_out_trailing_attribution(self):
        self.add("<h1>f</h1><p>Does f.</p>" + self.ATTR)
        r = self.cli("show", "lib:f")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Does f.", r.stdout)
        self.assertNotIn("Licensed", r.stdout)
        self.assertNotIn("example.org", r.stdout)

    def test_fts_does_not_index_attribution(self):
        self.add("<h1>f</h1><p>Does f.</p>" + self.ATTR)
        r = self.cli("fts", "Licensed", "-d", "lib")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("lib:f", r.stdout)

    def test_attribution_class_mid_page_is_kept(self):
        self.add("<h1>f</h1>" + self.ATTR + "<p>Does f.</p>")
        r = self.cli("show", "lib:f")
        self.assertIn("Licensed", r.stdout)


def add_listed_only(cache, slug, name):
    """Add a row to the cached DevDocs list without installing it."""
    path = os.path.join(cache, "devdocs", "docs.json")
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    rows.append({"name": name, "slug": slug, "type": slug.split("~")[0],
                 "version": "", "release": "1", "mtime": 1700000000,
                 "db_size": 1, "attribution": "", "alias": None, "links": {}})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f)


class InstallHintTests(unittest.TestCase):
    """A docvol name that DevDocs lists but isn't installed says how to
    install it (from the cached list; never the network)."""

    def setUp(self):
        SearchTests.setUp(self)
        make_devdocs(self.cache, "alpha", name="Alpha", release="1",
                     entries=[("x", "Function", "x")], pages={"x": "<p>t</p>"})
        add_listed_only(self.cache, "duckdb", "DuckDB")

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def test_scope_name_listed_by_devdocs_says_install(self):
        r = self.cli("search", "x", "-d", "DuckDB")
        self.assertEqual(r.returncode, 4)
        self.assertEqual(r.stderr.strip(), "docvol 'DuckDB' is not installed; "
                         "DevDocs has it: docshelf.py install duckdb")

    def test_ref_docvol_listed_by_devdocs_says_install(self):
        r = self.cli("show", "duckdb:a")
        self.assertEqual(r.returncode, 5)
        self.assertIn("docshelf.py install duckdb", r.stderr)

    def test_name_devdocs_does_not_list_keeps_unknown_message(self):
        r = self.cli("search", "x", "-d", "nope")
        self.assertEqual(r.returncode, 4)
        self.assertIn("unknown docvol 'nope'", r.stderr)
        self.assertNotIn("install", r.stderr)


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


class _FakeDocvol(shelf_core.Docvol):
    """In-memory docvol for backend-interface tests."""
    HTML = "<h1 id='f'>f</h1><p>body</p>"

    def __init__(self, data_dir, html=None):
        self.name = "fake"
        self.family = "fake"
        self.title = "Fake"
        self.release = "1"
        self.source = "folder"
        self._dir = data_dir
        self._html = html or self.HTML
        self.entry_count = 1

    def entries(self):
        return [shelf_core.Entry("f", "Function", "fake:p#f", "p", "f")]

    def pages(self):
        return ["p"]

    def page_html(self, page):
        if page != "p":
            raise CLIError("no page %s" % page, 5)
        return self._html

    def resolve(self, rest):
        page, _, anchor = rest.partition("#")
        return page, anchor or None, self.entries()[0] if rest in ("p", "p#f") else None

    def make_ref(self, page, anchor):
        return "fake:%s%s" % (page, "#" + anchor if anchor else "")

    def stamp(self):
        return "1"

    def data_dir(self):
        return self._dir


class FamilyScopeTests(unittest.TestCase):
    NOTE = ("note: searching 2 docvols of python (python~3.11, python~3.12); "
            "-d NAME picks one")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": self.cache,
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def add(self, slug, entries=None):
        entries = entries if entries is not None else [("x", "Function", "x")]
        pages = {e[2].partition("#")[0]: "<p>t</p>" for e in entries}
        make_devdocs(self.cache, slug, name=slug.capitalize(), release="1",
                     entries=entries, pages=pages)

    def cli(self, *args, project=None):
        if project is not None:
            with open(os.path.join(self.tmp, ".docshelf.json"), "w") as f:
                json.dump(project, f)
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def add_python_and_lua(self):
        for slug in ("python~3.11", "python~3.12", "lua~5.4"):
            self.add(slug)

    def test_family_selects_all_versions(self):
        self.add_python_and_lua()
        r = self.cli("search", "x", "-d", "python")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], self.NOTE)
        self.assertTrue(any(l.startswith("python~3.11:") for l in lines))
        self.assertTrue(any(l.startswith("python~3.12:") for l in lines))
        self.assertFalse(any(l.startswith("lua~5.4:") for l in lines))

    def test_exact_name_selects_one(self):
        self.add_python_and_lua()
        r = self.cli("search", "x", "-d", "python~3.12")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("note:", r.stdout)
        self.assertNotIn("python~3.11", r.stdout)
        self.assertIn("python~3.12:", r.stdout)

    def test_json_note_goes_to_stderr(self):
        self.add_python_and_lua()
        r = self.cli("search", "x", "-d", "python", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsInstance(json.loads(r.stdout), list)
        self.assertIn(self.NOTE, r.stderr)

    def test_project_list_family(self):
        self.add_python_and_lua()
        r = self.cli("search", "x", project={"docvols": ["python"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("python~3.11:", r.stdout)
        self.assertIn("python~3.12:", r.stdout)
        self.assertNotIn("lua~5.4:", r.stdout)

    def test_scope_error_lists_families(self):
        big = [("x", "Function", "a")] + [
            ("f%d" % i, "Function", "p%d" % i) for i in range(500)]
        for slug in ("a~1", "a~2", "b", "c", "d"):
            self.add(slug, big)
        r = self.cli("search", "x")
        self.assertEqual(r.returncode, 4)
        self.assertIn("a (2), b, c, d", r.stderr)


class BackendInterfaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "DOCSHELF_CACHE_DIR": os.path.join(self.tmp, "cache"),
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def run_main(self, fake, *args):
        import shelf_backends
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env), \
                mock.patch.object(shelf_backends, "installed_docvols",
                                  return_value=[fake]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def fake(self, cls=_FakeDocvol, html=None):
        return cls(os.path.join(self.tmp, "fakedata"), html)

    def test_commands_use_the_backend_aggregator(self):
        f = self.fake()
        for args, want in ((("list",), "fake"),
                           (("search", "f", "-d", "fake"), "fake:p#f"),
                           (("show", "fake:p"), "body")):
            code, out, err = self.run_main(f, *args)
            self.assertEqual(code, 0, err)
            self.assertIn(want, out)

    def test_show_link_uses_resolve_href(self):
        class F(_FakeDocvol):
            def resolve_href(self, page, href):
                return "fake:other"
        f = self.fake(F, "<h1 id='f'>f</h1><p><a href='x'>x</a></p>")
        code, out, err = self.run_main(f, "show", "fake:p")
        self.assertEqual(code, 0, err)
        self.assertIn("[fake:other]", out)

    def test_page_blocks_is_used_by_fts_and_headings(self):
        class F(_FakeDocvol):
            def page_blocks(self, page, link=None):
                return [b for b in super().page_blocks(page, link)
                        if "DROPME" not in b.text]
        f = self.fake(F, "<h1 id='f'>f</h1><h2 id='d'>DROPME</h2><p>body</p>")
        code, out, err = self.run_main(f, "fts", "DROPME", "-d", "fake")
        self.assertIn("no matches", out)
        code, out, err = self.run_main(f, "notes", "fake", "--check")
        self.assertNotIn("DROPME", out)
        self.assertEqual(f.page_blocks("p")[0].text.strip("# "), "f")


class DashReaderTests(unittest.TestCase):
    ENTRIES = [("open", "Function", "lib.html#open"), ("os", "Module", "os.html")]
    PAGES = {"lib.html": "<h1>lib</h1>", "os.html": "<h1>os</h1>"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache = os.path.join(self.tmp, "cache")

    def docvol(self, name="Lib", **kw):
        kw.setdefault("entries", self.ENTRIES)
        kw.setdefault("pages", self.PAGES)
        path = make_docset(self.tmp, name, **kw)
        return shelf_dash.DashDocvol(path, "dash", self.cache)

    def test_search_index_entries_and_refs(self):
        dv = self.docvol()
        got = [(e.ref, e.page, e.anchor) for e in dv.entries()]
        self.assertEqual(got, [("Lib:1", "lib.html", "open"),
                               ("Lib:2", "os.html", None)])
        self.assertEqual(dv.entry_count, 2)
        self.assertEqual(dv.pages(), ["lib.html", "os.html"])
        self.assertTrue(dv.read_only)
        self.assertIn("<h1>os</h1>", dv.page_html("os.html"))
        self.assertEqual(dv.make_ref("os.html", "top"), "Lib:page:os.html#top")
        self.assertEqual(dv.resolve_href("lib.html", "os.html#x"),
                         "Lib:page:os.html#x")
        self.assertIsNone(dv.resolve_href("lib.html", "nope.html"))

    def test_ztoken_form_reads_the_same(self):
        a = self.docvol("A")
        b = self.docvol("B", form="ztoken")
        key = lambda dv: [(e.name, e.type, e.page, e.anchor) for e in dv.entries()]
        self.assertEqual(key(a), key(b))
        self.assertEqual(b.entry_count, 2)

    def test_marker_and_percent_paths(self):
        dv = self.docvol(entries=[("x", "Func", "<dash_entry_name=x>a%20b.html#x"),
                                  ("c", "Func", "sub\\c.html")], pages={})
        got = [(e.page, e.anchor) for e in dv.entries()]
        self.assertEqual(got, [("a b.html", "x"), ("sub/c.html", None)])

    def test_url_rows_are_not_entries(self):
        dv = self.docvol(entries=self.ENTRIES + [("x", "Guide", "https://example.org/x")])
        self.assertEqual(len(dv.entries()), 2)
        self.assertEqual(dv.pages(), ["lib.html", "os.html"])

    def test_resolve_forms(self):
        dv = self.docvol()
        page, anchor, entry = dv.resolve("1")
        self.assertEqual((page, anchor, entry.ref), ("lib.html", "open", "Lib:1"))
        self.assertEqual(dv.resolve("page:os.html#top"), ("os.html", "top", None))
        with self.assertRaises(CLIError) as c:
            dv.resolve("x")
        self.assertEqual(c.exception.code, 2)
        self.assertIn("bad reference", str(c.exception))
        with self.assertRaises(CLIError) as c:
            dv.resolve("99")
        self.assertEqual(c.exception.code, 5)

    def test_path_outside_documents_refused(self):
        dv = self.docvol(plist_name="Lib")
        with self.assertRaises(CLIError) as c:
            dv.page_html("../Info.plist")
        self.assertEqual(c.exception.code, 5)

    def test_title_version_family(self):
        dv = self.docvol("Python_3", plist_name="Python 3", meta_version="3.12.4")
        self.assertEqual((dv.title, dv.display_name, dv.version, dv.release),
                         ("Python 3", "Python 3", "3.12.4", "3.12.4"))
        self.assertEqual(dv.family, "python")
        plain = self.docvol("Plain")
        self.assertEqual((plain.title, plain.version), ("Plain", ""))
        self.assertEqual([shelf_dash.dash_family(n) for n in
                          ("Node.js", "Qt_6.5", "Foo Bar-2")],
                         ["node.js", "qt", "foo_bar"])

    def test_version_from_name_without_meta(self):
        got = [self.docvol(n).version for n in ("Python_3", "Qt_6.5", "Plain")]
        self.assertEqual(got, ["3", "6.5", ""])
        same = shelf_backends.same_documentation
        ns = lambda v, ro: types.SimpleNamespace(family="python", version=v,
                                                 read_only=ro)
        self.assertTrue(same(ns("3", True), ns("3.12", False)))
        self.assertTrue(same(ns("3.12.1", True), ns("3.12", False)))
        self.assertFalse(same(ns("2", True), ns("3.12", False)))
        self.assertFalse(same(ns("3.12", True), ns("3.13", False)))

    def test_symlink_out_of_documents_refused(self):
        dv = self.docvol()
        outside = os.path.join(self.tmp, "secret.html")
        with open(outside, "w") as f:
            f.write("<p>secret</p>")
        try:
            os.symlink(outside, os.path.join(dv.docs_dir, "evil.html"))
            os.symlink(os.path.join(dv.docs_dir, "os.html"),
                       os.path.join(dv.docs_dir, "alias.html"))
        except (OSError, NotImplementedError) as e:
            self.skipTest("symlinks not permitted here: %s" % e)
        with self.assertRaises(CLIError) as c:
            dv.page_html("evil.html")
        self.assertEqual(c.exception.code, 5)
        self.assertIsNone(dv.resolve_href("lib.html", "evil.html"))
        self.assertIn("<h1>os</h1>", dv.page_html("alias.html"))

    def test_wal_rows_are_read(self):
        dv = self.docvol(wal=True)
        res = os.path.join(dv.path, "Contents", "Resources")
        self.assertTrue(os.path.getsize(os.path.join(res, "docSet.dsidx-wal")) > 0)
        self.assertEqual(dv.entry_count, 2)
        self.assertEqual([e.ref for e in dv.entries()], ["Lib:1", "Lib:2"])
        self.assertIn("-", dv.stamp())

    def test_wal_in_read_only_folder_uses_a_copy(self):
        dv = self.docvol(wal=True)
        real = shelf_dash._open_ro

        def refuse_original(path):  # what mode=ro does with no -shm file
            if os.path.abspath(path) == dv.index_file:
                raise sqlite3.OperationalError("unable to open database file")
            return real(path)

        with mock.patch.object(shelf_dash, "_open_ro", refuse_original):
            again = shelf_dash.DashDocvol(dv.path, "dash", self.cache)
            self.assertEqual(len(again.entries()), 2)
        self.assertTrue(os.path.isfile(  # (closing our copy checkpoints its -wal)
            os.path.join(again.data_dir(), "index", "docSet.dsidx")))

    def test_malformed_info_plist_falls_back_to_name(self):
        path = make_docset(self.tmp, "Junk", self.ENTRIES, self.PAGES)
        with open(os.path.join(path, "Contents", "Info.plist"), "wb") as f:
            f.write(b"<?xml version='1.0'?><plist><dict><key>x")
        dv = shelf_dash.open_docset(path, "dash", self.cache)
        self.assertIsNotNone(dv)
        self.assertEqual(dv.title, "Junk")

    def test_unreadable_index_is_skipped(self):
        path = make_docset(self.tmp, "Bad", [], {})
        open(os.path.join(path, "Contents", "Resources", "docSet.dsidx"), "w").close()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            dv = shelf_dash.open_docset(path, "dash", self.cache)
        self.assertIsNone(dv)
        lines = err.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("warning: skipping"))


class DashTarixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = make_docset(self.tmp, "Lib", [("os", "Module", "os.html")],
                           {"os.html": "<h1>os</h1>"})
        self.files = {"os.html": b"<h1>os</h1>", "sub/a.html": b"<p>a</p>"}
        make_tarix(path, self.files)
        self.path = path
        self.dv = shelf_dash.DashDocvol(path, "dash", os.path.join(self.tmp, "cache"))

    def test_page_read_from_tarix(self):
        self.assertFalse(os.path.exists(os.path.join(
            self.path, "Contents", "Resources", "Documents")))
        self.assertEqual(self.dv.page_html("os.html"), "<h1>os</h1>")
        self.assertEqual(self.dv.page_html("sub/a.html"), "<p>a</p>")

    def test_tarix_missing_page_exit_5(self):
        for page in ("nope.html", "../tarixIndex.db"):
            with self.assertRaises(CLIError) as cm:
                self.dv.page_html(page)
            self.assertEqual(cm.exception.code, 5)

    def test_tarix_link_resolves(self):
        self.assertEqual(self.dv.resolve_href("os.html", "SUB/a.html#x"),
                         "Lib:page:SUB/a.html#x")
        self.assertIsNone(self.dv.resolve_href("os.html", "nope.html"))

    def test_wal_tarix_index_read_from_a_copy(self):
        res = os.path.join(self.path, "Contents", "Resources")
        idx = os.path.join(res, "tarixIndex.db")
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        shutil.copyfile(idx, os.path.join(work, "t.db"))
        con = sqlite3.connect(os.path.join(work, "t.db"))
        try:  # rows rewritten into the -wal, copied while the writer is open
            con.execute("PRAGMA journal_mode=wal")
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("UPDATE tarindex SET hash = hash")
            con.commit()
            for suffix in ("", "-wal"):
                shutil.copyfile(os.path.join(work, "t.db" + suffix), idx + suffix)
        finally:
            con.close()

        def snapshot():
            out = []
            for dirpath, dirs, files in os.walk(self.path):
                for n in dirs + files:
                    p = os.path.join(dirpath, n)
                    st = os.stat(p)
                    out.append((os.path.relpath(p, self.path), st.st_size,
                                st.st_mtime_ns))
            return sorted(out)

        before = snapshot()
        dv = shelf_dash.DashDocvol(self.path, "dash", os.path.join(self.tmp, "cache"))
        self.assertEqual(dv.page_html("sub/a.html"), "<p>a</p>")
        self.assertEqual(dv.resolve_href("os.html", "sub/a.html"), "Lib:page:sub/a.html")
        self.assertEqual(snapshot(), before)
        self.assertTrue(os.path.isfile(os.path.join(dv.data_dir(), "tarix", "tarixIndex.db")))

    def test_corrupt_tarix_entry_exit_7(self):
        con = sqlite3.connect(os.path.join(
            self.path, "Contents", "Resources", "tarixIndex.db"))
        try:
            con.execute("UPDATE tarindex SET hash = '0 0 999999999'")
            con.commit()
        finally:
            con.close()
        with self.assertRaises(CLIError) as cm:
            self.dv.page_html("os.html")
        self.assertEqual(cm.exception.code, 7)


class DashDiscoveryTests(unittest.TestCase):
    ENTRIES = [("frobnicate", "Function", "api.html#frob")]
    PAGES = {"api.html": "<h1 id=\"frob\">frobnicate</h1><p>Frobs it.</p>"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        for d in ("home", "data", "config", "local", "path", "work"):
            os.makedirs(os.path.join(self.tmp, d))
        self.home = os.path.join(self.tmp, "home")
        self.work = os.path.join(self.tmp, "work")
        self.env = {
            "HOME": self.home, "USERPROFILE": self.home,
            "LOCALAPPDATA": os.path.join(self.tmp, "local"),
            "XDG_DATA_HOME": os.path.join(self.tmp, "data"),
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
            "PATH": os.path.join(self.tmp, "path"),
            "DOCSHELF_CACHE_DIR": os.path.join(self.tmp, "cache"),
            "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    def docset(self, root, name="Lib"):
        os.makedirs(root, exist_ok=True)
        return make_docset(root, name, self.ENTRIES, self.PAGES)

    def zeal_dir(self):
        return os.path.join(self.env["XDG_DATA_HOME"], "Zeal", "Zeal", "docsets")

    def cli(self, *args, **env):
        return run_cli(*args, env=dict(self.env, **env), cwd=self.work)

    def listed(self, **env):
        r = self.cli("list", **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [ln.split("  ") for ln in r.stdout.splitlines()]

    def test_zeal_linux_default_folder(self):
        self.docset(self.zeal_dir(), "Frob")
        rows = self.listed()
        self.assertEqual([(r[0], r[-1]) for r in rows], [("Frob", "zeal")])
        s = self.cli("search", "frobnicate", "-d", "Frob")
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertIn("Frob:1", s.stdout)
        sh = self.cli("show", "Frob:1")
        self.assertEqual(sh.returncode, 0, sh.stderr)
        self.assertIn("Frobs it.", sh.stdout)

    def test_dash_macos_folder(self):
        self.docset(os.path.join(self.home, "Library", "Application Support",
                                 "Dash", "DocSets", "X"), "X")
        rows = self.listed()
        self.assertEqual([(r[0], r[-1]) for r in rows], [("X", "dash")])

    def test_dash_windows_package(self):
        pkg = os.path.join(self.env["LOCALAPPDATA"], "Packages",
                           "Kapeli.Dash_abc123")
        self.docset(os.path.join(pkg, "LocalState", "DocSets"), "Y")
        os.makedirs(os.path.join(self.env["LOCALAPPDATA"], "Packages", "Other.App_1"))
        rows = self.listed()
        self.assertEqual([(r[0], r[-1]) for r in rows], [("Y", "dash")])
        w = self.cli("where")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertRegex(w.stdout, r"apps: .*Dash \(")
        self.assertIn("Kapeli.Dash_abc123", w.stdout)

    def test_zeal_custom_path_from_conf(self):
        custom = os.path.join(self.tmp, "custom")
        self.docset(custom, "Cust")
        conf = os.path.join(self.env["XDG_CONFIG_HOME"], "Zeal")
        os.makedirs(conf)
        with open(os.path.join(conf, "Zeal.conf"), "w") as f:
            f.write("[docsets]\npath=%s\n" % custom)
        rows = self.listed()
        self.assertEqual([(r[0], r[-1]) for r in rows], [("Cust", "zeal")])

    def test_env_dirs_first_and_shadowing(self):
        mine = os.path.join(self.tmp, "mine")
        self.docset(mine)
        zeal_copy = self.docset(self.zeal_dir())
        rows = self.listed(DOCSHELF_DOCSET_DIRS=mine)
        self.assertEqual([(r[0], r[-1]) for r in rows], [("Lib", "folder")])
        w = self.cli("where", DOCSHELF_DOCSET_DIRS=mine)
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("shadowed", w.stdout)
        self.assertIn(zeal_copy, w.stdout)

    def test_same_folder_two_spellings_is_one_folder(self):
        mine = os.path.join(self.tmp, "mine")
        self.docset(mine)
        dirs = mine + os.pathsep + mine + os.sep
        rows = self.listed(DOCSHELF_DOCSET_DIRS=dirs)
        self.assertEqual([(r[0], r[-1]) for r in rows], [("Lib", "folder")])
        w = self.cli("where", DOCSHELF_DOCSET_DIRS=dirs)
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertNotIn("shadowed", w.stdout)
        self.assertEqual(sum(1 for ln in w.stdout.splitlines()
                             if ln.strip().startswith(mine)), 1)

    def test_missing_env_dir_is_reported_not_fatal(self):
        gone = os.path.join(self.tmp, "gone")
        self.assertEqual(self.cli("list", DOCSHELF_DOCSET_DIRS=gone).returncode, 0)
        w = self.cli("where", DOCSHELF_DOCSET_DIRS=gone)
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("%s (missing)" % gone, w.stdout)

    def test_where_reports_no_apps(self):
        w = self.cli("where")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("apps: none found", w.stdout)
        self.assertIn("docset folders:", w.stdout)

    def test_docset_name_equal_to_devdocs_is_skipped_with_warning(self):
        make_devdocs(self.env["DOCSHELF_CACHE_DIR"], "Lib", name="Lib", release="1",
                     entries=self.ENTRIES, pages=self.PAGES)
        self.docset(self.zeal_dir(), "Lib")
        r = self.cli("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x.split("  ")[-1] for x in r.stdout.splitlines()], ["devdocs"])
        self.assertIn("Lib", r.stderr)
        self.assertIn("same name", r.stderr)

    def test_docset_over_mcp(self):
        self.docset(self.zeal_dir(), "Frob")
        proc = subprocess.Popen(
            [sys.executable, SCRIPT, "--mcp"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=dict(clean_env(), **self.env), cwd=self.work)
        self.addCleanup(lambda: (proc.stdin.close(), proc.wait(timeout=10),
                                 proc.stdout.close(), proc.stderr.close()))
        counter = [0]

        def call(name, arguments):
            counter[0] += 1
            proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "id": counter[0], "method": "tools/call",
                 "params": {"name": name, "arguments": arguments}}) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())["result"]

        found = call("search", {"query": ["frobnicate"], "docvols": ["Frob"]})
        self.assertFalse(found["isError"], found)
        cli = self.cli("search", "frobnicate", "-d", "Frob")
        self.assertEqual(found["content"][0]["text"], cli.stdout)
        shown = call("show", {"ref": "Frob:1"})
        self.assertFalse(shown["isError"], shown)
        self.assertIn("Frobs it.", shown["content"][0]["text"])


class DashFooterTests(unittest.TestCase):
    FOOT = "<p>&copy; Example</p><p>Licensed under the Example License.</p>"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.docs = os.path.join(self.tmp, "docs")
        os.makedirs(self.docs)
        self.env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
                    "XDG_DATA_HOME": os.path.join(self.tmp, "data"),
                    "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
                    "LOCALAPPDATA": os.path.join(self.tmp, "local"),
                    "PATH": os.path.join(self.tmp, "path"),
                    "DOCSHELF_DOCSET_DIRS": self.docs,
                    "DOCSHELF_CACHE_DIR": os.path.join(self.tmp, "cache"),
                    "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}

    HEAD = "<p>Skip to main content</p><p>Menu</p>"

    def build(self, count, footers=None, headers=None, extra=None):
        """count pages p1..pN, each with a header, unique body text, then a
        footer; extra maps more page names to their whole HTML."""
        pages, entries = {}, []
        for i in range(1, count + 1):
            foot = footers(i) if footers else self.FOOT
            head = headers(i) if headers else ""
            pages["p%d.html" % i] = "%s<h1>Page%d</h1><p>Body%d text.</p>%s" % (
                head, i, i, foot)
            entries.append(("item%d" % i, "Function", "p%d.html" % i))
        for page, html in (extra or {}).items():
            pages[page] = html
            entries.append((page, "Guide", page))
        make_docset(self.docs, "Lib", entries, pages)

    def cli(self, *args):
        return run_cli(*args, env=self.env, cwd=self.tmp)

    def show(self, page):
        r = self.cli("show", "Lib:page:" + page, "--full")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_repeated_footer_left_out_but_kept_once(self):
        self.build(6)
        self.assertNotIn("Licensed under", self.show("p2.html"))
        self.assertNotIn("\u00a9 Example", self.show("p2.html"))
        self.assertIn("Body2 text.", self.show("p2.html"))
        keeper = self.show("p1.html")
        self.assertIn("Licensed under the Example License.", keeper)
        self.assertIn("\u00a9 Example", keeper)
        r = self.cli("fts", "Licensed", "-d", "Lib")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("Lib:"), 1, r.stdout)

    def test_no_footer_when_pages_differ(self):
        self.build(6, lambda i: "<p>Ends differently %d.</p>" % i)
        for i in (1, 2, 5):
            self.assertIn("Ends differently %d." % i, self.show("p%d.html" % i))

    def test_too_few_pages_no_detection(self):
        self.build(4)
        self.assertIn("Licensed under", self.show("p2.html"))

    def test_repeated_header_left_out_but_kept_once(self):
        self.build(6, footers=lambda i: "", headers=lambda i: self.HEAD)
        p2 = self.show("p2.html")
        self.assertNotIn("Skip to main content", p2)
        self.assertNotIn("Menu", p2)
        self.assertIn("Body2 text.", p2)
        self.assertEqual(p2.splitlines()[0], "# Page2")  # the page's own title
        r = self.cli("show", "Lib:2", "--full")  # an entry: no wrong "(page: ...)"
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("(page:", r.stdout)
        self.assertNotIn("Skip to main content", r.stdout)
        keeper = self.show("p1.html")
        self.assertIn("Skip to main content", keeper)
        self.assertIn("Menu", keeper)
        r = self.cli("fts", "Skip to main content", "-d", "Lib")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("Lib:"), 1, r.stdout)

    def test_no_header_when_first_blocks_differ(self):
        self.build(6, headers=lambda i: "<p>Starts differently %d.</p>" % i)
        for i in (1, 2, 5):
            self.assertIn("Starts differently %d." % i, self.show("p%d.html" % i))

    def test_header_and_footer_both_left_out(self):
        self.build(6, headers=lambda i: self.HEAD)
        p3 = self.show("p3.html")
        for gone in ("Skip to main content", "Menu", "Licensed under"):
            self.assertNotIn(gone, p3)
        self.assertIn("# Page3", p3)
        self.assertIn("Body3 text.", p3)

    def test_header_after_a_per_page_title_block(self):
        skip = ('<ul><li><a href="#c">Skip to main content</a></li>'
                '<li><a href="#s">Skip to search</a></li></ul>')
        pages = {"p%d.html" % i: "<html><head><title>Title %d</title></head><body>"
                 "%s<h1>H%d</h1><p>Body%d text.</p></body></html>" % (i, skip, i, i)
                 for i in range(1, 7)}
        make_docset(self.docs, "Lib", [("item%d" % i, "Function", "p%d.html" % i)
                                       for i in range(1, 7)], pages)
        p2 = self.show("p2.html")
        self.assertNotIn("Skip to", p2)
        self.assertEqual(p2.splitlines()[:2], ["Title 2", "# H2"])
        self.assertIn("Body2 text.", p2)
        keeper = self.show("p1.html")
        self.assertIn("Skip to main content", keeper)
        self.assertIn("Skip to search", keeper)
        r = self.cli("fts", "Skip to search", "-d", "Lib")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("Lib:"), 1, r.stdout)

    def test_page_of_only_header_and_footer_is_not_emptied(self):
        self.build(6, headers=lambda i: self.HEAD,
                   extra={"bare.html": self.HEAD + self.FOOT})
        bare = self.show("bare.html")
        self.assertIn("Skip to main content", bare)
        self.assertIn("Menu", bare)


class InstallProjectListTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.docs = os.path.join(self.tmp, "docsets")
        self.work = os.path.join(self.tmp, "work")
        for d in (os.path.join(self.cache, "devdocs"), self.docs, self.work):
            os.makedirs(d)
        env = mock.patch.dict(os.environ, {
            "HOME": self.tmp, "USERPROFILE": self.tmp,
            "XDG_DATA_HOME": os.path.join(self.tmp, "data"),
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
            "LOCALAPPDATA": os.path.join(self.tmp, "local"),
            "PATH": os.path.join(self.tmp, "path"),
            "DOCSHELF_DOCSET_DIRS": self.docs,
            "DOCSHELF_CACHE_DIR": self.cache,
            "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")})
        env.start()
        self.addCleanup(env.stop)
        old = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, old)
        entries = [("Intro", "Guide", "intro")]
        pages = {"intro": "<h1>Intro</h1>"}
        rows = [row("Lua", "lua~5.4", "5.4.6", version="5.4"),
                row("Python", "python~3.12", "3.12.1", version="3.12")]
        allp = {shelf_devdocs.MANIFEST_URL: json.dumps(rows)}
        for r in rows:
            allp.update(remote_docvol(r["slug"], entries, pages))
        self.net = FakeNet(self, allp)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def project(self, names):
        with open(os.path.join(self.work, ".docshelf.json"), "w") as f:
            json.dump({"docvols": names}, f)

    def have(self):
        return sorted(os.listdir(os.path.join(self.cache, "devdocs")))

    def test_install_project_list(self):
        self.main("install", "python~3.12")
        self.project(["lua", "python"])
        code, out, err = self.main("install")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("installed lua~5.4", out)
        self.assertIn("python: installed\n", out)
        self.assertIn("lua~5.4", self.have())

    def test_install_project_list_skips_docset(self):
        make_docset(self.docs, "HTTP", [("frob", "Function", "api.html")],
                    {"api.html": "<h1>frob</h1>"}, meta_version="1.0")
        self.project(["http"])
        code, out, err = self.main("install")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "http: Dash/Zeal docset HTTP, "
                              "not installed from DevDocs\n")

    def test_install_project_list_unknown_name_continues(self):
        self.project(["nosuchdoc", "lua"])
        code, out, err = self.main("install")
        self.assertEqual(code, 5)
        self.assertIn("nosuchdoc", err)
        self.assertIn("installed lua~5.4", out)
        self.assertIn("lua~5.4", self.have())

    def test_install_no_names_no_project_list(self):
        code, out, err = self.main("install")
        self.assertEqual(code, 2)
        self.assertIn('install needs NAME (or a "docvols" list in '
                      '.docshelf.json)', err)


class DashReadOnlyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.docs = os.path.join(self.tmp, "docsets")
        os.makedirs(os.path.join(self.cache, "devdocs"))
        os.makedirs(self.docs)
        env = mock.patch.dict(os.environ, {
            "HOME": self.tmp, "USERPROFILE": self.tmp,
            "XDG_DATA_HOME": os.path.join(self.tmp, "data"),
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
            "LOCALAPPDATA": os.path.join(self.tmp, "local"),
            "PATH": os.path.join(self.tmp, "path"),
            "DOCSHELF_DOCSET_DIRS": self.docs,
            "DOCSHELF_CACHE_DIR": self.cache,
            "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")})
        env.start()
        self.addCleanup(env.stop)
        self.entries = [("Intro", "Guide", "intro")]
        self.pages = {"intro": "<h1>Intro</h1>"}
        rows = [row("Python", "python~3.12", "3.12.1", version="3.12"),
                row("Python", "python~3.11", "3.11.5", version="3.11")]
        pages = {shelf_devdocs.MANIFEST_URL: json.dumps(rows)}
        for r in rows:
            pages.update(remote_docvol(r["slug"], self.entries, self.pages))
        self.net = FakeNet(self, pages)

    def docset(self, name="Python_3", version="3.12.1"):
        return make_docset(self.docs, name, [("frob", "Function", "api.html")],
                           {"api.html": "<h1>frob</h1>"}, meta_version=version)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_bare_update_with_only_docsets_says_so(self):
        self.docset()
        code, out, _err = self.main("update")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "no DevDocs docvols to update (Dash/Zeal "
                         "docsets are updated in Dash or Zeal)")

    def snapshot(self, folder):
        found = []
        for dirpath, _, files in os.walk(folder):
            for f in files:
                p = os.path.join(dirpath, f)
                found.append((p, os.stat(p).st_mtime_ns))
        return sorted(found)

    def test_install_refuses_redundant_without_force(self):
        self.docset()
        code, out, err = self.main("install", "python~3.12")
        self.assertEqual(code, 2, (out, err))
        self.assertIn("python~3.12: Dash/Zeal docset Python_3 has this "
                      "documentation and is used as is; install --force "
                      "python~3.12 downloads it anyway", err)
        self.assertEqual(self.net.fetched, [shelf_devdocs.MANIFEST_URL])
        code, out, err = self.main("install", "python~3.12", "--force")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("installed python~3.12"), out)

    def test_install_other_version_is_not_redundant(self):
        self.docset()
        code, out, err = self.main("install", "python~3.11")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("installed python~3.11"), out)

    def test_unknown_docset_version_counts_as_same(self):
        self.docset(version=None)
        code, out, err = self.main("install", "python~3.12")
        self.assertEqual(code, 2, (out, err))
        self.assertIn("Dash/Zeal docset Python_3 has this documentation", err)

    def test_name_version_python_2_does_not_block_3_12(self):
        self.docset("Python_2", version=None)
        code, out, err = self.main("install", "python~3.12")
        self.assertEqual((code, err), (0, ""))

    def test_name_version_python_3_blocks_every_3_x(self):
        self.docset("Python_3", version=None)
        for slug in ("python~3.12", "python~3.11"):
            code, out, err = self.main("install", slug)
            self.assertEqual(code, 2, (slug, out, err))
            self.assertIn("Dash/Zeal docset Python_3 has this documentation", err)

    def test_remove_and_update_refuse_docsets(self):
        folder = self.docset()
        before = self.snapshot(folder)
        for cmd in ("remove", "update"):
            code, out, err = self.main(cmd, "Python_3")
            self.assertEqual(code, 2, (cmd, out, err))
            self.assertIn("Python_3 is a Dash/Zeal docset; Dash or Zeal "
                          "manages it", err)
        self.assertEqual(self.main("update")[0], 0)
        self.assertEqual(self.snapshot(folder), before)

    def test_list_flags_redundant_pairs(self):
        self.docset()
        self.assertEqual(self.main("install", "python~3.12", "--force")[0], 0)
        code, out, err = self.main("list")
        self.assertEqual(code, 0, err)
        lines = {ln.split("  ")[0]: ln for ln in out.splitlines()}
        self.assertTrue(lines["python~3.12"].endswith(
            "  devdocs  also as docset Python_3"), out)
        self.assertTrue(lines["Python_3"].endswith(
            "  also as DevDocs python~3.12"), out)


class DashCatalogTests(unittest.TestCase):
    """`sources` lists Dash/Zeal docset names (GitHub listings, Zeal's catalog
    as fallback) when Dash or Zeal is around; the not-installed hint reads the
    cached catalogs."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(os.path.join(self.cache, "devdocs"))
        self.data = os.path.join(self.tmp, "data")
        env = mock.patch.dict(os.environ, {
            "HOME": self.tmp, "USERPROFILE": self.tmp,
            "XDG_DATA_HOME": self.data,
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"),
            "LOCALAPPDATA": os.path.join(self.tmp, "local"),
            "PATH": os.path.join(self.tmp, "path"),
            "DOCSHELF_CACHE_DIR": self.cache,
            "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")})
        env.start()
        self.addCleanup(env.stop)
        rows = [row("Python", "python~3.12", "3.12.1", version="3.12")]
        self.feeds = json.dumps([
            {"name": "Python_3.xml", "type": "file"},
            {"name": "README.md", "type": "file"},
            {"name": "Lua_5.xml", "type": "file"}])
        self.contrib = json.dumps([{"name": "Lua", "type": "dir"},
                                   {"name": "notes.txt", "type": "file"}])
        self.zeal = json.dumps([
            {"name": "Python_3", "title": "Python 3", "sourceId": "com.kapeli.dash",
             "versions": ["3.12"], "icon": "x" * 50},
            {"name": "Lua", "title": "Lua", "sourceId": "com.kapeli.contrib"}])
        self.net = FakeNet(self, {
            shelf_devdocs.MANIFEST_URL: json.dumps(rows),
            shelf_dash.FEEDS_LIST_URL: self.feeds,
            shelf_dash.CONTRIB_LIST_URL: self.contrib,
            shelf_dash.ZEAL_CATALOG_URL: self.zeal})

    def zeal_install(self):
        os.makedirs(os.path.join(self.data, "Zeal", "Zeal", "docsets"))

    def catalog_urls(self):
        return [u for u in self.net.fetched
                if u != shelf_devdocs.MANIFEST_URL]

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_sources_lists_catalog_names_when_app_present(self):
        self.zeal_install()
        code, out, _ = self.main("sources", "python")
        self.assertEqual(code, 0)
        self.assertIn("python~3.12", out)
        self.assertIn("Python_3  (Dash/Zeal: download in the app, official)\n", out)
        self.assertNotIn("Lua", out)
        out = self.main("sources", "lua")[1]
        self.assertIn("Lua  (Dash/Zeal: download in the app, user-contributed)", out)

    def test_sources_no_catalog_without_app_or_folder(self):
        code, out, _ = self.main("sources", "python")
        self.assertEqual(code, 0)
        self.assertEqual(self.catalog_urls(), [])
        self.assertNotIn("Dash/Zeal", out)

    def test_zeal_catalog_fallback(self):
        self.zeal_install()
        for u in (shelf_dash.FEEDS_LIST_URL, shelf_dash.CONTRIB_LIST_URL):
            self.net.pages[u] = shelf_devdocs.NetError(u, "blocked")
        code, out, err = self.main("sources", "python")
        self.assertEqual(code, 0)
        self.assertIn("Python_3  (Dash/Zeal: download in the app, official)", out)
        self.assertIn("Zeal's catalog", err)
        self.assertIn(shelf_dash.ZEAL_CATALOG_URL, self.net.fetched)

    def test_zeal_catalog_fetched_once_per_run_on_refresh(self):
        self.zeal_install()
        for u in (shelf_dash.FEEDS_LIST_URL, shelf_dash.CONTRIB_LIST_URL):
            self.net.pages[u] = shelf_devdocs.NetError(u, "blocked")
        code, out, _err = self.main("sources", "python", "--refresh")
        self.assertEqual(code, 0)
        self.assertIn("Python_3  (Dash/Zeal: download in the app, official)", out)
        self.assertEqual(self.net.fetched.count(shelf_dash.ZEAL_CATALOG_URL), 1)

    def test_failing_zeal_catalog_fetched_once_per_run(self):
        self.zeal_install()
        for u in (shelf_dash.FEEDS_LIST_URL, shelf_dash.CONTRIB_LIST_URL,
                  shelf_dash.ZEAL_CATALOG_URL):
            self.net.pages[u] = shelf_devdocs.NetError(u, "blocked")
        self.main("sources", "python")
        self.assertEqual(self.net.fetched.count(shelf_dash.ZEAL_CATALOG_URL), 1)

    def test_catalog_failure_keeps_devdocs_part(self):
        self.zeal_install()
        for u in (shelf_dash.FEEDS_LIST_URL, shelf_dash.CONTRIB_LIST_URL,
                  shelf_dash.ZEAL_CATALOG_URL):
            self.net.pages[u] = shelf_devdocs.NetError(u, "blocked")
        code, out, err = self.main("sources", "python")
        self.assertEqual(code, 0)
        self.assertIn("python~3.12", out)
        self.assertNotIn("Dash/Zeal:", out)
        self.assertIn("note: the Dash/Zeal official list could not be loaded", err)
        self.assertIn("note: the Dash/Zeal user-contributed list could not be loaded",
                      err)

    def test_catalog_cached_for_a_week(self):
        self.zeal_install()
        self.main("sources", "python")
        self.main("sources", "lua")
        self.assertEqual(sorted(self.catalog_urls()),
                         sorted([shelf_dash.FEEDS_LIST_URL,
                                 shelf_dash.CONTRIB_LIST_URL]))

    def test_not_installed_hint_from_cached_catalog(self):
        self.zeal_install()
        cdir = os.path.join(self.cache, "docsets", "catalogs")
        os.makedirs(cdir)
        with open(os.path.join(cdir, "contrib-list.json"), "w") as f:
            json.dump(["Lua"], f)
        code, _, err = self.main("search", "x", "-d", "Lua")
        self.assertEqual(code, 4)
        self.assertIn("Dash/Zeal can download docset 'Lua'", err)
        self.assertIn("docshelf doesn't install docsets", err)
        self.assertEqual(self.net.fetched, [])
        code, _, err = self.main("show", "lua:x")
        self.assertEqual(code, 5)
        self.assertIn("Dash/Zeal can download docset 'Lua'", err)

    def test_not_installed_hint_needs_an_app(self):
        cdir = os.path.join(self.cache, "docsets", "catalogs")
        os.makedirs(cdir)
        with open(os.path.join(cdir, "contrib-list.json"), "w") as f:
            json.dump(["Lua"], f)
        code, _, err = self.main("search", "x", "-d", "Lua")
        self.assertEqual(code, 4)
        self.assertIn("unknown docvol 'Lua'", err)

    def test_allowlist_lists_exactly_the_hosts_used(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                            "skills", "docshelf", "assets", "allowlist.txt")
        with open(path, encoding="utf-8") as f:
            listed = {ln.strip() for ln in f
                      if ln.strip() and not ln.lstrip().startswith("#")}
        urls = [shelf_devdocs.MANIFEST_URL, shelf_devdocs.DOCUMENTS_BASE,
                shelf_dash.FEEDS_LIST_URL, shelf_dash.CONTRIB_LIST_URL,
                shelf_dash.ZEAL_CATALOG_URL]
        from urllib.parse import urlsplit
        self.assertEqual(listed, {urlsplit(u).hostname for u in urls})
        self.assertEqual(listed, {"devdocs.io", "documents.devdocs.io",
                                  "api.github.com", "api.zealdocs.org"})

    def test_net_error_names_host_without_fixed_list(self):
        e = shelf_devdocs.NetError("https://api.github.com/x", "HTTP 403")
        self.assertIn("api.github.com", str(e))
        self.assertIn("assets/allowlist.txt", str(e))
        self.assertNotIn("(devdocs.io", str(e))


class DashWalCopyTests(unittest.TestCase):
    """A WAL index is read from a copy in the cache: nothing is written into
    the docset folder (no -shm is created or touched)."""
    ENTRIES = [("open", "Function", "lib.html#open"), ("os", "Module", "os.html")]
    PAGES = {"lib.html": "<h1>lib</h1><p>Opens files.</p>",
             "os.html": "<h1>os</h1><p>Operating system calls.</p>"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.docs = os.path.join(self.tmp, "docs")
        self.cache = os.path.join(self.tmp, "cache")
        self.path = make_docset(self.docs, "Lib", self.ENTRIES, self.PAGES, wal=True)
        shm = os.path.join(self.path, "Contents", "Resources", "docSet.dsidx-shm")
        if os.path.exists(shm):  # as downloaded: index and -wal only
            os.remove(shm)

    def snapshot(self):
        out = []
        for dirpath, dirs, files in os.walk(self.path):
            for n in dirs + files:
                p = os.path.join(dirpath, n)
                st = os.stat(p)
                out.append((os.path.relpath(p, self.path), st.st_size, st.st_mtime_ns))
        return sorted(out)

    def open(self):
        return shelf_dash.DashDocvol(self.path, "folder", self.cache)

    def test_docset_folder_unchanged(self):
        before = self.snapshot()
        dv = self.open()
        self.assertEqual([e.ref for e in dv.entries()], ["Lib:1", "Lib:2"])
        self.assertEqual(dv.entry_count, 2)
        self.assertIn("Opens files.", dv.page_html("lib.html"))
        env = {"HOME": self.tmp, "USERPROFILE": self.tmp,
               "DOCSHELF_DOCSET_DIRS": self.docs, "DOCSHELF_CACHE_DIR": self.cache,
               "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")}
        r = run_cli("fts", "Operating", "-d", "Lib", env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Lib:", r.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_copy_reused_until_the_wal_changes(self):
        dv = self.open()
        self.assertEqual(len(dv.entries()), 2)
        copy = os.path.join(dv.data_dir(), "index", "docSet.dsidx")
        self.assertTrue(os.path.isfile(copy))
        real_copy = shutil.copyfile
        with mock.patch.object(shelf_dash.shutil, "copyfile", wraps=real_copy) as cp:
            self.assertEqual(len(self.open().entries()), 2)
        self.assertEqual(cp.call_count, 0)
        con = sqlite3.connect(dv.index_file)  # a writer adds a row to the -wal
        try:
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("INSERT INTO searchIndex (name, type, path) "
                        "VALUES ('sys', 'Module', 'os.html')")
            con.commit()
            with mock.patch.object(shelf_dash.shutil, "copyfile", wraps=real_copy) as cp:
                self.assertEqual(len(self.open().entries()), 3)
            self.assertGreater(cp.call_count, 0)
        finally:
            con.close()


class DashLazyTests(unittest.TestCase):
    """Discovery opens no docset index; only commands that need a docset's
    rows or entry count read it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.cache = os.path.join(self.tmp, "cache")
        self.docs = os.path.join(self.tmp, "docsets")
        make_devdocs(self.cache, "alpha", name="Alpha", release="1",
                     entries=[("frob", "Function", "a")],
                     pages={"a": "<h1>frob</h1><p>Frobs.</p>"})
        make_docset(self.docs, "Lib", [("frob", "Function", "api.html"),
                                       ("grub", "Function", "api.html")],
                    {"api.html": "<h1>frob</h1>"}, wal=True)
        env = mock.patch.dict(os.environ, {
            "HOME": self.tmp, "USERPROFILE": self.tmp,
            "DOCSHELF_DOCSET_DIRS": self.docs, "DOCSHELF_CACHE_DIR": self.cache,
            "DOCSHELF_NOTES_DIR": os.path.join(self.tmp, "notes")})
        env.start()
        self.addCleanup(env.stop)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = shelf_cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def watch(self):
        """Patch the index readers to count calls (still working)."""
        conn = mock.patch.object(shelf_dash.DashDocvol, "_connect", autospec=True,
                                 side_effect=shelf_dash.DashDocvol._connect)
        copy = mock.patch.object(shelf_dash.shutil, "copyfile",
                                 wraps=shutil.copyfile)
        return conn, copy

    def test_search_other_docvol_never_reads_the_docset_index(self):
        conn, copy = self.watch()
        with conn as c, copy as cp:
            code, out, err = self.main("search", "frob", "-d", "alpha")
        self.assertEqual(code, 0, err)
        self.assertIn("frob", out)
        self.assertEqual((c.call_count, cp.call_count), (0, 0))

    def test_list_reads_the_count_once_then_caches_it(self):
        code, out, err = self.main("list")
        self.assertEqual(code, 0, err)
        line = next(ln for ln in out.splitlines() if ln.startswith("Lib  "))
        self.assertIn("  2 entries  ", line)
        conn, copy = self.watch()
        with conn as c, copy:
            code, out2, err = self.main("list")
        self.assertEqual((code, out2), (0, out))
        self.assertEqual(c.call_count, 0)


class EnvIsolationTests(unittest.TestCase):
    """In-process tests never see the developer's real docsets or apps."""

    def test_module_setup_drops_xdg_and_system_apps(self):
        self.assertEqual([k for k in os.environ if k.startswith("XDG_")], [])
        self.assertEqual(shelf_dash.SYSTEM_APP_PATHS, ())
        self.assertIsNone(shelf_dash._zeal_registry_path())

    def test_probe_in_process_list(self):
        """Run in a child below with XDG_DATA_HOME set in its parent env."""
        with tempfile.TemporaryDirectory() as cache:
            with mock.patch.dict(os.environ, {"DOCSHELF_CACHE_DIR": cache}):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(shelf_cli.main(["list"]), 0)
        self.assertNotIn("Leaky", out.getvalue())

    def test_parent_xdg_data_home_is_ignored(self):
        with tempfile.TemporaryDirectory() as data:
            make_docset(os.path.join(data, "Zeal", "Zeal", "docsets"), "Leaky",
                        [("x", "Function", "x.html")], {"x.html": "<p>x</p>"})
            env = dict(os.environ, XDG_DATA_HOME=data)
            r = subprocess.run(
                [sys.executable, "-m", "unittest",
                 "test_docshelf.EnvIsolationTests.test_probe_in_process_list"],
                capture_output=True, text=True, env=env,
                cwd=os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ran 1 test", r.stderr)
        self.assertNotIn("skipped", r.stderr)

    def test_no_system_apps_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = os.path.join(tmp, "Zeal.app")
            os.makedirs(app)
            with mock.patch.object(shelf_dash, "SYSTEM_APP_PATHS", (("Zeal", app),)):
                self.assertEqual(shelf_dash.viewer_apps({"PATH": _EMPTY}),
                                 [("Zeal", app)])
                self.assertEqual(shelf_dash.viewer_apps(
                    {"PATH": _EMPTY, "DOCSHELF_NO_SYSTEM_APPS": "1"}), [])


class StructureNotSkippedTests(unittest.TestCase):
    """html, body, main and article are page structure: a skip class, a
    navigation role or the hidden attribute on them must not empty the page."""

    def text(self, html):
        return [b.text for b in shelf_render.html_to_text(html)]

    def test_body_with_skip_class_keeps_content(self):
        html = '<body class="sidebar-drawer"><h1 id="a">A</h1><p>text</p></body>'
        self.assertIn("text", " ".join(self.text(html)))

    def test_main_with_navigation_role_keeps_content(self):
        html = '<main role="navigation"><h1 id="a">A</h1><p>text</p></main>'
        self.assertIn("text", " ".join(self.text(html)))

    def test_article_hidden_keeps_content(self):
        html = '<article hidden><h1 id="a">A</h1><p>text</p></article>'
        self.assertIn("text", " ".join(self.text(html)))

    def test_div_with_skip_class_still_skipped(self):
        html = '<div class="sphinxsidebar">nav</div><p>x</p>'
        out = " ".join(self.text(html))
        self.assertIn("x", out)
        self.assertNotIn("nav", out)

    def test_show_body_with_skip_class_keeps_content(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_dir = os.path.realpath(tmp.name)
        cache = os.path.join(tmp_dir, "cache")
        make_devdocs(cache, "b", name="B", release="1",
                     entries=[("Page", "Guide", "p")],
                     pages={"p": '<body class="sidebar-drawer"><h1 id="a">A</h1>'
                                 "<p>text</p></body>"})
        env = {"HOME": tmp_dir, "USERPROFILE": tmp_dir,
               "DOCSHELF_CACHE_DIR": cache,
               "DOCSHELF_NOTES_DIR": os.path.join(tmp_dir, "notes")}
        r = run_cli("show", "b:p", "--no-notes", env=env, cwd=tmp_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("text", r.stdout)


if __name__ == "__main__":
    unittest.main()
