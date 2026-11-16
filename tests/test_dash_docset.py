"""Offline tests for skills/dash-docset/scripts/docset.py.

No network: docsets are built by make_docset() in temp dirs. Run from the
repo root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import plistlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

if not selected("dash-docset"):
    raise unittest.SkipTest("dash-docset not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "skills", "dash-docset", "scripts", "docset.py")

spec = importlib.util.spec_from_file_location("docset", SCRIPT)
docset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docset)

SUBCOMMANDS = ["where", "sources", "list", "remove",
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


LEAKY_ENV = ("DASH_DOCSET_DIR", "DASHT_DOCSETS_DIR", "APPDATA", "LOCALAPPDATA",
             "OLDPWD")


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

    def test_top_help_is_the_command_reference(self):
        import re
        r = run_cli("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(run_cli().returncode, 2)  # no command: same text, exit 2
        head, _, rare = r.stdout.partition("Only if you need these")
        opts = docset.subcommand_options(docset.build_parser())
        for name, common in docset.COMMON_OPTIONS.items():
            for o in common:
                self.assertIn(o, opts[name], "%s %s is not a real option" % (name, o))
                self.assertIn(o, head, "common %s %s missing from the command lines"
                              % (name, o))
        # every other option is named in the generated list, on its command's line
        rare_lines = {l.split()[0]: l.split()[1:] for l in rare.splitlines()[1:]
                      if l.startswith("  ") and l.split()}
        for name, all_opts in opts.items():
            for o in all_opts:
                if o not in docset.COMMON_OPTIONS.get(name, set()):
                    self.assertIn(o, rare_lines.get(name, []), "%s %s" % (name, o))
        for line in r.stdout.splitlines():
            self.assertLessEqual(len(line), 80, line)

    def test_docs_mention_only_real_options(self):
        import glob
        import re
        skill = os.path.dirname(os.path.dirname(SCRIPT))
        known = {"--help", "--dir", "--version"}
        for o in docset.subcommand_options(docset.build_parser()).values():
            known.update(o)
        known.update({"--docset"})  # long form of -d
        files = [os.path.join(skill, "SKILL.md")] + glob.glob(
            os.path.join(skill, "references", "*.md"))
        for path in files:
            with open(path, encoding="utf-8") as f:
                for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", f.read()):
                    self.assertIn(flag, known, "%s: %s" % (os.path.basename(path), flag))

    def test_version(self):
        import re
        self.assertRegex(docset.VERSION, r"^\d+\.\d+\.\d+$")
        # unambiguous, so a server can filter or rate-limit it (the user)
        self.assertEqual(docset.USER_AGENT, f"docset-agent-skill-RJS/{docset.VERSION}")
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
        self.assertEqual(listed, used)  # no stale hosts either

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
        self.assertIn("references/setup.md", r.stdout)
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
        self.assertIn("references/setup.md", str(cm.exception))
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


class ProjectFileFallbackTests(unittest.TestCase):
    """Where .dash-docset.json is looked for when the current folder has none
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
                    "XDG_CONFIG_HOME": os.path.join(self.home, "cfg"),
                    "XDG_DATA_HOME": os.path.join(self.home, "data")}
        self.user_cfg = os.path.join(self.env["XDG_CONFIG_HOME"],
                                     "dash-docset", "config.json")

    def write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def project(self, folder, store="s"):
        self.write_json(os.path.join(folder, ".dash-docset.json"), {"store": store})

    def script_copy(self, skill_dir):
        """A copy of the script at <skill_dir>/scripts/docset.py."""
        import shutil
        dest = os.path.join(skill_dir, "scripts", "docset.py")
        os.makedirs(os.path.dirname(dest))
        shutil.copy(SCRIPT, dest)
        return dest

    def run_script(self, script, *args, cwd, **env):
        full = clean_env()
        full.update(self.env)
        full.update(env)
        return subprocess.run([sys.executable, script, *args], capture_output=True,
                              text=True, env=full, cwd=cwd)

    def test_found_from_oldpwd(self):
        self.project(self.proj)
        r = self.run_script(SCRIPT, "where", cwd=self.other, OLDPWD=self.sub)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("store: " + os.path.join(self.proj, "s"), r.stdout)
        self.assertIn("source: project file", r.stdout)
        # says which file it used and why, since it isn't under the current folder
        self.assertIn(os.path.join(self.proj, ".dash-docset.json"), r.stderr)
        self.assertIn("OLDPWD", r.stderr)

    def test_found_from_script_folder(self):
        self.project(self.proj)
        script = self.script_copy(os.path.join(self.proj, ".claude", "skills", "dash-docset"))
        r = self.run_script(script, "where", cwd=self.other)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("store: " + os.path.join(self.proj, "s"), r.stdout)
        self.assertIn("script", r.stderr)

    def test_current_folder_wins_and_prints_no_note(self):
        self.project(self.proj, "mine")
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere)
        self.project(elsewhere, "theirs")
        r = self.run_script(SCRIPT, "where", cwd=self.sub, OLDPWD=elsewhere)
        self.assertIn("store: " + os.path.join(self.proj, "mine"), r.stdout)
        self.assertEqual(r.stderr, "")

    def test_script_folder_before_oldpwd(self):
        self.project(self.proj, "of-script")
        script = self.script_copy(os.path.join(self.proj, "skills", "dash-docset"))
        elsewhere = os.path.join(self.home, "elsewhere")
        os.makedirs(elsewhere)
        self.project(elsewhere, "of-oldpwd")
        r = self.run_script(script, "where", cwd=self.other, OLDPWD=elsewhere)
        self.assertIn("store: " + os.path.join(self.proj, "of-script"), r.stdout)

    def test_fallback_before_user_config(self):
        self.project(self.proj)
        self.write_json(self.user_cfg, {"store": os.path.join(self.tmp, "user-store")})
        r = self.run_script(SCRIPT, "where", cwd=self.other, OLDPWD=self.proj)
        self.assertIn("store: " + os.path.join(self.proj, "s"), r.stdout)

    def test_fallback_walk_checks_home_then_stops(self):
        # the home folder itself is checked ...
        self.project(self.home, "in-home")
        r = self.run_script(SCRIPT, "where", cwd=self.other, OLDPWD=self.sub)
        self.assertIn("store: " + os.path.join(self.home, "in-home"), r.stdout)
        # ... but nothing above it
        os.remove(os.path.join(self.home, ".dash-docset.json"))
        self.project(self.tmp, "above-home")
        outside = tempfile.TemporaryDirectory()  # not under self.tmp
        self.addCleanup(outside.cleanup)
        r = self.run_script(SCRIPT, "where", cwd=outside.name, OLDPWD=self.sub)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_walk_up_stops_below_users_folders(self):
        w = docset.walk_up
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
        self.assertEqual(list(w(os.path.join(os.sep, "opt", "skills", "x"), env)),
                         [os.path.join(os.sep, "opt", "skills", "x"),
                          os.path.join(os.sep, "opt", "skills"),
                          os.path.join(os.sep, "opt")])

    @unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc")
    def test_found_from_parent_process_folder(self):
        self.project(self.proj)
        full = clean_env()
        full.update(self.env)
        # outer sh stays in the project; inner sh changes folder; no OLDPWD
        inner = "cd %s && env -u OLDPWD %s %s where" % (self.other, sys.executable, SCRIPT)
        r = subprocess.run(["sh", "-c", "sh -c '%s'; true" % inner],
                           capture_output=True, text=True, env=full, cwd=self.sub)
        self.assertIn("store: " + os.path.join(self.proj, "s"), r.stdout, r.stderr)
        self.assertIn("parent process", r.stderr)

    def test_unset_message_names_where_it_looked(self):
        r = self.run_script(SCRIPT, "list", cwd=self.other, OLDPWD=self.sub)
        self.assertEqual(r.returncode, 3)
        self.assertIn(".dash-docset.json", r.stderr)
        self.assertIn(self.other, r.stderr)
        self.assertIn(self.sub, r.stderr)
        self.assertIn(self.user_cfg, r.stderr)
        r = self.run_script(SCRIPT, "where", cwd=self.other, OLDPWD=self.sub)
        self.assertEqual(r.returncode, 3)
        self.assertIn(self.other, r.stdout)

    def test_set_project_from_skill_folder_writes_to_previous_folder(self):
        skill = os.path.join(self.tmp, "skills", "dash-docset")
        script = self.script_copy(skill)
        r = self.run_script(script, "where", "--set", ".docsets", "--project",
                            cwd=skill, OLDPWD=self.proj)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.proj, ".dash-docset.json")))
        self.assertTrue(os.path.isdir(os.path.join(self.proj, ".docsets")))
        self.assertFalse(os.path.exists(os.path.join(skill, ".dash-docset.json")))
        self.assertFalse(os.path.exists(os.path.join(skill, ".docsets")))
        self.assertIn(self.proj, r.stdout + r.stderr)

    def test_set_project_from_skill_folder_without_a_project_folder_fails(self):
        skill = os.path.join(self.tmp, "skills", "dash-docset")
        script = self.script_copy(skill)
        r = self.run_script(script, "where", "--set", ".docsets", "--project",
                            cwd=os.path.join(skill, "scripts"), OLDPWD=skill)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("skill folder", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(skill, ".dash-docset.json")))
        self.assertFalse(os.path.exists(os.path.join(skill, "scripts", ".dash-docset.json")))

    def test_set_refuses_to_replace_another_store(self):
        self.project(self.proj, "old")
        cfg = os.path.join(self.proj, ".dash-docset.json")
        r = self.run_script(SCRIPT, "where", "--set", "new", "--project", cwd=self.proj)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(os.path.join(self.proj, "old"), r.stderr)
        self.assertIn("--replace", r.stderr)
        with open(cfg) as f:
            self.assertEqual(json.load(f), {"store": "old"})
        self.assertFalse(os.path.exists(os.path.join(self.proj, "new")))
        # the same store again is fine (e.g. to add --read-from)
        r = self.run_script(SCRIPT, "where", "--set", "old", "--project",
                            "--read-from", "../shared", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_script(SCRIPT, "where", "--set", "new", "--project", "--replace",
                            cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(cfg) as f:
            self.assertEqual(json.load(f)["store"], "new")

    def test_set_project_refuses_to_shadow_a_project_file_above(self):
        self.project(self.proj, "old")
        r = self.run_script(SCRIPT, "where", "--set", "new", "--project", cwd=self.sub)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(os.path.join(self.proj, ".dash-docset.json"), r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.sub, ".dash-docset.json")))

    def test_set_user_refuses_to_replace_another_store(self):
        self.write_json(self.user_cfg, {"store": os.path.join(self.tmp, "old")})
        r = self.run_script(SCRIPT, "where", "--set", os.path.join(self.tmp, "new"),
                            "--user", cwd=self.other)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--replace", r.stderr)
        r = self.run_script(SCRIPT, "where", "--set", os.path.join(self.tmp, "new"),
                            "--user", "--replace", cwd=self.other)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_discover_prints_the_store_in_use(self):
        r = self.run_script(SCRIPT, "where", "--discover", cwd=self.other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("store: not set", r.stdout)
        self.project(self.proj)
        r = self.run_script(SCRIPT, "where", "--discover", cwd=self.sub)
        self.assertIn("store: %s (project file)" % os.path.join(self.proj, "s"), r.stdout)


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


class TableSpanTests(unittest.TestCase):
    def test_colspan_cells_labelled(self):
        html = ("<table><tr><td>31</td><td>30</td><td>29</td></tr>"
                "<tr><td>1</td><td colspan='2'>Rm</td></tr>"
                "<tr><td colspan='3'></td></tr></table>")
        text = [b.text for b in docset.html_to_text(html)]
        self.assertIn("1 | Rm (2 cols)", text)
        self.assertFalse(any("cols" in t and "Rm" not in t for t in text))  # empty span


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

    def test_several_names_at_once_lists_the_best_entry_for_each_word(self):
        self.add("Alpha", [("date_diff(part, a, b)", "Function", "date.html#diff"),
                           ("date_diff_old", "Function", "date.html#old"),
                           ("date_sub(part, a, b)", "Function", "date.html#sub")])
        r = self.cli("search", "date_diff", "date_sub", "zzz", "-d", "Alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        # says why nothing matched: all the words must be in one name
        self.assertIn("one entry name", out[0])
        self.assertIn("'date_diff date_sub zzz'", out[0])
        self.assertIn("Alpha:1  Function  date_diff(part, a, b)", out)
        self.assertIn("Alpha:3  Function  date_sub(part, a, b)", out)
        self.assertNotIn("date_diff_old", r.stdout)  # one entry per word, the best
        self.assertTrue(any("'zzz'" in l and "no entry name" in l for l in out), out)

    def test_several_words_none_in_any_name_keeps_the_plain_message(self):
        self.add("Alpha", [("date_sub", "Function", "date.html#sub")])
        r = self.cli("search", "enemy", "arrow", "-d", "Alpha")
        self.assertTrue(r.stdout.startswith("no matches for 'enemy arrow' (entry names only"),
                        r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 1)

    def test_docset_name_is_case_insensitive(self):
        self.add("Alpha", [("date_sub", "Function", "date.html#sub")])
        r = self.cli("search", "date_sub", "-d", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Alpha:1", r.stdout)
        r = self.cli("search", "date_sub", project={"docsets": ["ALPHA"]})
        self.assertIn("Alpha:1", r.stdout)

    @unittest.skipIf(sys.platform in ("win32", "darwin"),
                     "needs a case-sensitive filesystem")
    def test_docset_name_exact_case_wins_when_two_differ_only_in_case(self):
        self.add("Alpha", [("date_sub", "Function", "date.html#sub")])
        self.add("ALPHA", [("other_fn", "Function", "o.html#x")])
        r = self.cli("search", "date_sub", "-d", "Alpha")
        self.assertIn("Alpha:1", r.stdout)
        r = self.cli("search", "date_sub", "-d", "alpha")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Alpha", r.stderr)
        self.assertIn("ALPHA", r.stderr)

    def test_anchored_signature_beats_bare_page_entry(self):
        self.add("Alpha", [("date_sub", "Function", "date.html"),
                           ("date_sub(part, a, b)", "Function", "date.html#sub"),
                           ("date_subx", "Function", "date.html#x")])
        out = self.cli("search", "date_sub", "-d", "Alpha").stdout.splitlines()
        names = [l.split("  ")[2] for l in out]
        # the bare page entry opens the same section: folded into the anchored
        # one, listed only in --json (same text; agents opened it to check)
        self.assertEqual(names, ["date_sub(part, a, b)", "date_subx"])
        self.assertNotIn("Alpha:1", "\n".join(out))

    def test_bare_entry_kept_when_no_anchored_twin_on_its_page(self):
        self.add("Alpha", [("date_sub", "Function", "other.html"),
                           ("date_sub(part, a, b)", "Function", "date.html#sub")])
        out = self.cli("search", "date_sub", "-d", "Alpha").stdout.splitlines()
        self.assertEqual([l.split("  ")[2] for l in out],
                         ["date_sub(part, a, b)", "date_sub"])
        self.assertNotIn("same section", out[0])
        r = self.cli("search", "date_sub", "-d", "Alpha", "--json")
        self.assertEqual(len(json.loads(r.stdout)), 2)

    def test_folded_entries_in_json(self):
        self.add("Alpha", [("date_sub", "Function", "date.html"),
                           ("date_sub(part, a, b)", "Function", "date.html#sub")])
        items = json.loads(self.cli("search", "date_sub", "-d", "Alpha",
                                    "--json").stdout)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["same_section"], ["Alpha:1"])

    def test_multi_word_queries(self):
        self.add("Alpha", [("hero:get_walking_speed()", "Method", "a.html"),
                           ("hero:set_walking_speed(speed)", "Method", "a.html"),
                           ("walking", "Guide", "b.html")])
        r = self.cli("search", "walking", "speed", "-d", "Alpha")  # unquoted
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(len(out), 2, out)
        self.assertTrue(all("walking_speed" in l for l in out))
        r = self.cli("search", "speed walking", "-d", "Alpha")  # any word order
        self.assertEqual(len(r.stdout.splitlines()), 2)
        if docset.fts_available():
            r = self.cli("fts", "walking", "speed", "-d", "Alpha")
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_fuzzy_hits_capped_when_real_hits_exist(self):
        entries = [("timer", "Function", "a.html")] + [
            ("t_i_m_e_r_%d" % n, "Function", "a.html") for n in range(9)]
        self.add("Alpha", entries)
        r = self.cli("search", "timer", "-d", "Alpha")
        out = r.stdout.splitlines()
        self.assertEqual(sum(1 for l in out if "t_i_m_e_r" in l), docset.FUZZY_SHOWN)
        # an exact match exists: the hidden fuzzy hits aren't mentioned
        self.assertEqual(out, ["Alpha:1  Function  timer"])
        self.add("Beta", [("timers", "Function", "a.html")] + entries[1:])
        r = self.cli("search", "timer", "-d", "Beta")  # no whole-word hit
        self.assertEqual(r.stdout.splitlines()[-1], "... 9 fuzzy matches hidden "
                         "(letters in order only, often unrelated)")
        self.add("Gamma", [("asyncio.gather", "Function", "a.html"),
                           ("g_a_t_h_e_r", "Function", "a.html")])
        r = self.cli("search", "gather", "-d", "Gamma")  # whole word in a dotted name
        self.assertEqual(r.stdout.splitlines(), ["Gamma:1  Function  asyncio.gather"])
        r = self.cli("search", "tmr", "-d", "Alpha")  # only fuzzy: none cut
        self.assertEqual(sum(1 for l in r.stdout.splitlines() if "t_i_m_e_r" in l), 9)

    def test_search_ranks_across_docsets(self):
        self.add("Alpha", [("sleep_long", "Function", "a.html"),
                           ("sleep", "Function", "b.html")])
        self.add("Beta", [("Sleep", "Guide", "c.html"), ("xsleepx", "Guide", "d.html"),
                          ("s_l_e_e_p", "Guide", "e.html")], form="ztoken")
        r = self.cli("search", "sleep")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        # fuzzy hits are hidden when real hits exist, silently with an exact one
        self.assertEqual(len(out), 4, out)
        names = [l.split("  ")[2] for l in out[:4]]
        self.assertEqual(names, ["Sleep", "sleep", "sleep_long", "xsleepx"])
        r = self.cli("search", "slp", "-d", "Alpha")
        self.assertTrue(r.stdout.startswith("no exact, prefix or substring matches"))
        r = self.cli("search", "qqq", "-d", "Alpha")
        self.assertTrue(r.stdout.startswith("no matches for 'qqq' (entry names only"))
        first = out[0].split("  ")
        self.assertEqual(first[1], "Guide")
        self.assertEqual(len(first), 3)  # no repeated "(Docset)" suffix
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
        self.assertIn("Beta:", r.stdout)
        self.assertNotIn("Alpha:", r.stdout)

    def test_scope_project_list(self):
        for n in "ABCDEF":
            self.add("Doc" + n, [("thing", "Function", "a.html")])
        r = self.cli("search", "thing", project={"docsets": ["DocB", "DocC"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(l.split(":")[0] for l in r.stdout.splitlines()),
                         ["DocB", "DocC"])

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
        self.assertIn("Good:", r.stdout)
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


class ShowGrepTests(unittest.TestCase):
    PAGE = ("<html><body><h2 id='params'>Parameters</h2><p>Options for read_csv.</p>"
            "<table><tr><th>Name</th><th>Type</th><th>Default</th></tr>"
            "<tr><td>header</td><td>BOOL</td><td>false</td></tr>"
            "<tr><td>sep</td><td>VARCHAR</td><td>,</td></tr>"
            "<tr><td>skip</td><td>BIGINT</td><td>0</td></tr>"
            "<tr><td>quote</td><td>VARCHAR</td><td>\"</td></tr></table>"
            "<p>Use SKIP to ignore leading lines.</p></body></html>")

    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store = os.path.join(self.tmp, "store")
        make_docset(self.store, "Duck", entries=[("Parameters", "Section", "p.html#params")],
                    pages={"p.html": self.PAGE})

    def cli(self, *args):
        return run_cli("--dir", self.store, *args, env={"HOME": self.tmp}, cwd=self.tmp)

    def test_grep_keeps_heading_table_header_and_matches(self):
        r = self.cli("show", "Duck:1", "--grep", "skip", "--no-notes")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("## Parameters"), lines)
        row = next(k for k, l in enumerate(lines) if "skip" in l and "BIGINT" in l)
        self.assertIn("Name", lines[row - 2])  # the table's header row, then "..."
        self.assertEqual(lines[row - 1], "...")
        self.assertIn("Use SKIP to ignore leading lines.", r.stdout)  # case-insensitive
        for gone in ("header", "VARCHAR", "Options for read_csv"):
            self.assertNotIn(gone, r.stdout)
        self.assertIn("...", lines)  # skipped runs are marked
        # says that nothing matching was left out
        self.assertEqual(lines[-1], "(all 2 lines containing 'skip' are shown; "
                                    "the section has 8 lines)")

    def test_grep_repeatable_and_no_match(self):
        r = self.cli("show", "Duck:1", "--grep", "skip", "--grep", "quote", "--no-notes")
        self.assertIn("BIGINT", r.stdout)
        self.assertIn("quote", r.stdout)
        r = self.cli("show", "Duck:1", "--grep", "zzz", "--no-notes")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("no lines match"), r.stdout)
        self.assertIn("drop --grep", r.stdout)

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

    def dl_cli(self, *args):
        make_docset(self.store, "Pan", entries=[("read_csv", "Function", "d.html#f")],
                    pages={"d.html": self.DL_PAGE})
        return self.cli("show", "Pan:1", "--no-notes", *args)

    def test_grep_on_a_definition_term_shows_its_definition(self):
        r = self.dl_cli("--grep", "on_bad_lines")
        self.assertEqual(r.returncode, 0, r.stderr)
        for kept in ("What to do with a bad line. Allowed values are:",
                     "- 'error', raise.", "- 'warn', warn and skip.",
                     "Changed in version 2.2."):
            self.assertIn(kept, r.stdout)
        # stops at the next term; the signature's own "definition" is the
        # whole section, too long to add
        self.assertNotIn("Process the file in chunks", r.stdout)
        self.assertNotIn("Read a file.", r.stdout)
        self.assertNotIn("long line", r.stdout)
        self.assertIn("read_csv(path, on_bad_lines='error'", r.stdout)  # still a match
        self.assertIn("(all 2 lines containing 'on_bad_lines' are shown", r.stdout)
        self.assertIn("definition", r.stdout.splitlines()[-1])

    def test_grep_long_definition_is_not_added(self):
        r = self.dl_cli("--grep", "long_one")
        self.assertIn("long_one", r.stdout)
        self.assertNotIn("long line", r.stdout)

    def test_grep_match_inside_a_definition_adds_nothing(self):
        r = self.dl_cli("--grep", "warn and skip")
        self.assertIn("- 'warn', warn and skip.", r.stdout)
        self.assertNotIn("Changed in version", r.stdout)

    def test_docset_name_in_ref_is_case_insensitive(self):
        r = self.cli("show", "duck:1", "--grep", "skip", "--no-notes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BIGINT", r.stdout)

    def test_grep_on_page_ref(self):
        r = self.cli("show", "Duck:page:p.html", "--grep", "skip", "--no-notes")
        self.assertIn("BIGINT", r.stdout)
        self.assertNotIn("VARCHAR", r.stdout)


class FooterTests(unittest.TestCase):
    FOOT = "<p>Copyright Example Corp.</p><p>Index | Search</p>"

    def make(self, n_pages, index="index.html"):
        tmp = tmp_dir(self)
        store = os.path.join(tmp, "store")
        pages = {"index.html": "<h1>Home</h1><p>welcome</p>" + self.FOOT}
        entries = [("Home", "Guide", "index.html")]
        for i in range(n_pages):
            pages["p%d.html" % i] = ("<h1>Page %d</h1><h2 id='f'>func%d</h2>"
                                     "<p>body %d</p>" % (i, i, i) + self.FOOT)
            entries.append(("func%d" % i, "Function", "p%d.html#f" % i))
        pages["odd.html"] = "<h1>Odd</h1><p>Copyright is discussed here.</p>"
        entries.append(("odd", "Guide", "odd.html"))
        path = make_docset(store, "Foot", entries=entries, pages=pages)
        if index:
            plist = os.path.join(path, "Contents", "Info.plist")
            with open(plist, "rb") as f:
                data = plistlib.load(f)
            data["dashIndexFilePath"] = index
            with open(plist, "wb") as f:
                plistlib.dump(data, f)
        return tmp, store

    def cli(self, tmp, store, *args):
        return run_cli("--dir", store, *args, env={"HOME": tmp}, cwd=tmp)

    def test_footer_stripped_except_on_index_page(self):
        tmp, store = self.make(8)
        r = self.cli(tmp, store, "show", "Foot:2", "--no-notes")  # func0, last section
        self.assertIn("body 0", r.stdout)
        self.assertNotIn("Copyright Example", r.stdout)
        self.assertNotIn("Index | Search", r.stdout)
        r = self.cli(tmp, store, "show", "Foot:page:p0.html", "--no-notes")
        self.assertNotIn("Copyright Example", r.stdout)
        r = self.cli(tmp, store, "show", "Foot:1", "--no-notes")  # the index page keeps it
        self.assertIn("Copyright Example", r.stdout)
        r = self.cli(tmp, store, "show", "Foot:10", "--no-notes")  # not a footer page
        self.assertIn("Copyright is discussed here.", r.stdout)
        if docset.fts_available():
            r = self.cli(tmp, store, "fts", "Example", "Corp", "-d", "Foot")
            refs = [l for l in r.stdout.splitlines() if l.startswith("Foot:")]
            self.assertEqual(refs, ["Foot:page:index.html"], r.stdout)  # only there

    def test_no_index_page_keeps_footer_on_first_entry_page(self):
        tmp, store = self.make(8, index=None)
        r = self.cli(tmp, store, "show", "Foot:1", "--no-notes")  # lowest id's page
        self.assertIn("Copyright Example", r.stdout)
        r = self.cli(tmp, store, "show", "Foot:3", "--no-notes")
        self.assertNotIn("Copyright Example", r.stdout)

    def test_small_docset_left_alone(self):
        tmp, store = self.make(2)
        r = self.cli(tmp, store, "show", "Foot:2", "--no-notes")
        self.assertIn("Copyright Example", r.stdout)


class AnchorlessShowTests(unittest.TestCase):
    def test_show_starts_at_heading_named_like_entry(self):
        tmp = tmp_dir(self)
        store = os.path.join(tmp, "store")
        page = ("<html><body><h1>Date Functions</h1><p>intro</p>"
                "<h4 id='date_subpart'>date_sub(part, a, b)</h4><p>signed length</p>"
                "<h4 id='other'>other()</h4><p>nope</p></body></html>")
        make_docset(store, "Duck", entries=[("date_sub", "Function", "d.html")],
                    pages={"d.html": page})
        r = run_cli("--dir", store, "show", "Duck:1", "--no-notes",
                    env={"HOME": tmp}, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "(page: Date Functions)")  # names the page
        self.assertTrue(lines[1].startswith("#### date_sub(part, a, b)"), r.stdout)
        self.assertIn("signed length", r.stdout)
        self.assertNotIn("intro", r.stdout)
        self.assertNotIn("nope", r.stdout)


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
        self.assertTrue(r.stdout.startswith("notes file present: "), r.stdout)
        self.assertEqual(r.stdout.splitlines()[-1], "ok")

    def test_notes_check_says_what_each_heading_matched(self):
        make_docset(self.store_dir, "Py")
        self.write_notes("Py", "## General\ng\n## asyncio.gather\nfn\n## Gather (Guide)\nx\n")
        r = self.cli("notes", "Py", "--check")
        self.assertEqual(r.returncode, 0, r.stdout)
        lines = r.stdout.splitlines()
        self.assertIn("## General: shown by every show of this docset", lines)
        self.assertIn("## asyncio.gather: shown by show Py:1", lines)
        self.assertIn("## Gather (Guide): shown by show Py:3", lines)

    def test_notes_file_not_present_messages_parallel(self):
        make_docset(self.store_dir, "Py")
        for args in (("notes", "Py"), ("notes", "Py", "--check")):
            r = self.cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("notes file not present: "), r.stdout)

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

    def test_notes_heading_without_arguments(self):
        self.write_notes("Lua", "## sol.timer.start\nreturn true to repeat\n")
        out = docset.notes_for(self.store_dir, "Lua",
                               "sol.timer.start([context], delay, callback)", "Function")
        self.assertIn("return true to repeat", out)
        names = {"sol.timer.start([context], delay, callback)", "hero:freeze()"}
        self.assertEqual(docset.check_notes("## sol.timer.start\nx\n", names), [])
        warns = docset.check_notes("## sol.timer.stat\nx\n", names)
        self.assertEqual(len(warns), 1)
        self.assertIn("part before '('", warns[0])
        self.assertIn("did you mean 'sol.timer.start", warns[0])

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
        self.assertIn("Py:1\n", r.stdout)  # the match is at entry 1's anchor
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

    def test_fts_entry_ref_via_second_id(self):
        page = ("<html><body><h2><a name='//apple_ref/cpp/Guide/Params'></a>"
                "<span id='params'>Params</span></h2><p>skip lines at the start</p>"
                "</body></html>")
        make_docset(self.store_dir, "Duck", entries=[("Params", "Guide", "p.html#params")],
                    pages={"p.html": page})
        r = self.cli("fts", "skip", "lines", "-d", "Duck")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "Duck:1")

    def test_unquote_all_matches_double_encoded_anchors(self):
        self.assertEqual(docset._unquote_all("Guide/Out%2520of%2520Memory"),
                         "Guide/Out of Memory")
        self.assertEqual(docset._unquote_all("plain"), "plain")

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

    def test_fts_default_is_five_hits_with_hint(self):
        pages = {"p%02d.html" % i: "<p>needle %s</p>" % ("x " * i) for i in range(8)}
        make_docset(self.store_dir, "Many", pages=pages,
                    entries=[("x%d" % i, "Guide", p) for i, p in enumerate(pages)])
        r = self.cli("fts", "needle", "-d", "Many")
        lines = r.stdout.splitlines()
        self.assertEqual(sum(1 for l in lines if l.startswith("Many:")), 5, lines)
        self.assertIn("more hits cut", lines[-1])
        self.assertIn("add words", lines[-1])

    def test_fts_rebuilds_index_of_older_format(self):
        self.cli("fts", "gather", "-d", "Py")
        db = docset.fts_path(docset.Store(self.store_dir, "--dir", [], None), "Py")
        con = sqlite3.connect(db)
        con.execute("UPDATE meta SET value='old' WHERE key='docset_version'")
        con.commit()
        con.close()
        r = self.cli("fts", "gather", "-d", "Py")
        self.assertIn("rebuilt index for Py", r.stderr)

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


# --- sources, remove, the network ------------------------------------------

import contextlib  # noqa: E402
import io  # noqa: E402
import tarfile  # noqa: E402
from unittest import mock  # noqa: E402

CONTRIB = json.dumps([{"name": n, "type": "dir"} for n in
                      ("Solarus", "Arm_Morello_A64_ISA", "Ruby_on_Rails", "Foo")]
                     + [{"name": "README.md", "type": "file"}])
CATALOG = json.dumps([
    {"name": "Python", "title": "Python", "sourceId": "com.kapeli.dash",
     "versions": ["3.12"], "icon": "x" * 100},
    {"name": "Git", "title": "Git", "sourceId": "com.kapeli.cheatsheet",
     "versions": ["2"]},
    {"name": "Arm_Morello_A64_ISA", "title": "Arm Morello A64 ISA",
     "sourceId": "com.kapeli.contrib", "versions": ["2022.01"],
     "archive": "Arm_Morello_A64_ISA.tgz"}])


class FakeNet:
    """Replaces fetch / fetch_cond; records the calls."""

    def __init__(self, test, pages=None):
        self.pages = dict(pages or {})
        self.fetched = []
        self.cond = []  # (url, etag, last_modified) of conditional requests
        for name, fn in (("fetch", self.fetch), ("fetch_cond", self.fetch_cond)):
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


class NetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tmp_dir(self)
        self.store_dir = os.path.join(self.tmp, "store")
        os.makedirs(self.store_dir)
        self.store = docset.Store(self.store_dir, "flag", [], None)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docset.main(["--dir", self.store_dir] + list(argv))
        return code, out.getvalue(), err.getvalue()

    # kapeli.com is never contacted (Kapeli asked; the user, 2026-11-16)

    def test_request_refuses_kapeli(self):
        def no_net(*a, **k):
            raise AssertionError("network used")
        with mock.patch.object(docset.urllib.request, "urlopen", no_net), \
                mock.patch.object(docset.urllib.request.OpenerDirector, "open", no_net):
            for url in ("https://kapeli.com/feeds/zzz/cheatsheets/Git.tgz",
                        "http://london.kapeli.com/feeds/Python.tgz",
                        "https://KAPELI.COM./x", "https://kapeli.com:443/x"):
                with self.subTest(url=url):
                    with self.assertRaises(docset.FetchError) as cm:
                        docset.fetch(url)
                    self.assertIn("kapeli.com", str(cm.exception))
        self.assertFalse(docset.blocked_host("https://notkapeli.com/x"))
        self.assertFalse(docset.blocked_host("https://raw.githubusercontent.com/Kapeli/x"))

    def test_redirect_to_kapeli_refused(self):
        h = docset.NoBlockedRedirect()
        req = docset.urllib.request.Request("https://example.com/a")
        with self.assertRaises(docset.FetchError):
            h.redirect_request(req, None, 302, "Found", {},
                               "https://sanfrancisco.kapeli.com/feeds/x.tgz")
        ok = h.redirect_request(req, None, 302, "Found", {}, "https://example.com/b")
        self.assertEqual(ok.full_url, "https://example.com/b")

    def test_redirect_handler_in_use(self):
        seen = []

        class Opener:
            def open(self, req, timeout=None):
                seen.append(req.full_url)
                raise docset.urllib.error.URLError("offline")
        with mock.patch.object(docset, "_opener", lambda: Opener()):
            with self.assertRaises(docset.FetchError):
                docset.fetch("https://example.com/a")
        self.assertEqual(seen, ["https://example.com/a"])
        handlers = docset._opener().handlers
        self.assertTrue(any(isinstance(x, docset.NoBlockedRedirect) for x in handlers))

    def test_no_kapeli_urls_in_script(self):
        with open(SCRIPT, encoding="utf-8") as f:
            text = f.read()
        hosts = {urlsplit(u).hostname for u in re.findall(r"https?://[^\s\"'()<>]+", text)}
        self.assertFalse({h for h in hosts if h and docset.blocked_host("https://" + h)})
        for gone in ("Kapeli/feeds", "Kapeli/cheatsheets", "cheat.json",
                     "user_contributed/build"):
            self.assertNotIn(gone, text)

    def test_install_and_update_removed(self):
        net = FakeNet(self)
        for argv in (["install", "kapeli:Python"], ["install", "Foo"], ["update"]):
            with self.subTest(argv=argv):
                code, out, err = self.main(*argv)
                self.assertEqual(code, 2)
                self.assertIn("Dash", err)
                self.assertIn("Zeal", err)
                self.assertIn("sources", err)
        self.assertEqual(net.fetched + net.cond, [])

    # sources: the contributed docset list, from GitHub; Zeal's catalog last

    def test_sources_lists_contributed_from_github(self):
        net = FakeNet(self, pages={docset.CONTRIB_LIST_URL: CONTRIB})
        code, out, err = self.main("sources", "ruby", "on")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "Ruby_on_Rails")
        self.assertNotIn("Solarus", out)
        self.assertNotIn("README", out)
        self.assertIn("Dash", out)
        self.assertIn("Zeal", out)
        self.assertEqual([u for u, _e, _l in net.cond], [docset.CONTRIB_LIST_URL])
        self.main("sources", "solarus")  # cached for a week
        self.assertEqual(len(net.cond), 1)
        self.main("sources", "--refresh", "solarus")
        self.assertEqual(len(net.cond), 2)

    def test_sources_marks_docsets_already_here(self):
        FakeNet(self, pages={docset.CONTRIB_LIST_URL: CONTRIB})
        make_docset(self.store_dir, "Solarus")
        code, out, err = self.main("sources", "sol")
        self.assertEqual(code, 0, err)
        self.assertIn("Solarus  (already here", out)

    def test_sources_no_match(self):
        FakeNet(self, pages={docset.CONTRIB_LIST_URL: CONTRIB})
        code, out, err = self.main("sources", "python")
        self.assertEqual(code, 5)
        self.assertIn("no contributed docset matches 'python'", out)
        self.assertIn("Dash", out)

    def test_sources_falls_back_to_zeal_catalog(self):
        net = FakeNet(self, pages={docset.ZEAL_CATALOG_URL: CATALOG})
        net.etags = {docset.ZEAL_CATALOG_URL: '"v1"'}
        code, out, err = self.main("sources")
        self.assertEqual(code, 0, err)
        self.assertIn("Arm_Morello_A64_ISA  2022.01  (Arm Morello A64 ISA)", out)
        self.assertNotIn("Python", out)  # official and cheat sheets are not listed
        self.assertNotIn("Git", out)
        self.assertIn("Zeal's catalog", err)
        code, out, err = self.main("sources", "morello a64")  # title words match
        self.assertIn("Arm_Morello_A64_ISA", out)
        body = os.path.join(self.store_dir, ".dash-docset", "cache", "zeal-catalog.body")
        with open(body) as f:
            self.assertNotIn("icon", f.read())  # cached without icons
        zeal = lambda: sum(u == docset.ZEAL_CATALOG_URL for u, _e, _l in net.cond)
        self.assertEqual(zeal(), 1)
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

    def test_sources_all_failing(self):
        FakeNet(self)
        code, out, err = self.main("sources")
        self.assertEqual(code, 7)
        self.assertIn("cannot load the contributed docset list", err)

    def test_failed_fetch_not_retried_within_a_day(self):
        net = FakeNet(self)
        for _ in range(2):
            with self.assertRaises(docset.FetchError):
                docset.cached_get(self.store, "k", "https://x.example/a", 10)
        self.assertEqual(net.fetched, ["https://x.example/a"])

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

        class Opener:
            def __init__(self, result=None, error=None):
                self.result, self.error = result, error

            def open(self, req, timeout=None):
                if self.error:
                    raise self.error
                return self.result
        with mock.patch.object(docset, "_opener", lambda: Opener(Resp())):
            with self.assertRaises(docset.FetchError):
                docset.fetch("https://x.example/a")
        with mock.patch.object(docset, "_opener",
                               lambda: Opener(error=http.client.BadStatusLine("x"))):
            with self.assertRaises(docset.FetchError):
                docset.fetch("https://x.example/a")

    # remove: still works for docsets an earlier version installed

    def installed_foo(self):
        make_docset(self.store_dir, "Foo")
        docset.save_installed(self.store, {"Foo": {
            "source": "kapeli", "version": "1.0",
            "url": "https://one.example.com/feeds/Foo.tgz", "installed": "2026-11-14"}})

    def test_remove_keeps_notes(self):
        self.installed_foo()
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

    def test_remove_refuses_foreign(self):
        ro = os.path.join(self.tmp, "ro")
        os.makedirs(ro)
        make_docset(ro, "Alien")
        make_docset(self.store_dir, "Loose")  # in store, not in installed.json
        cfg = os.path.join(self.tmp, "proj")
        os.makedirs(cfg)
        with open(os.path.join(cfg, docset.PROJECT_FILE), "w") as f:
            json.dump({"store": self.store_dir, "read_from": [ro]}, f)
        old = os.getcwd()
        os.chdir(cfg)
        self.addCleanup(os.chdir, old)
        for name in ("Alien", "Loose"):
            with self.subTest(name=name):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = docset.main(["remove", name])
                self.assertEqual(code, 2, err.getvalue())
                self.assertIn("not installed by docset.py", err.getvalue())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = docset.main(["remove", "Nope"])
        self.assertEqual(code, 5)
        self.assertTrue(os.path.isdir(os.path.join(ro, "Alien.docset")))
        self.assertTrue(os.path.isdir(os.path.join(self.store_dir, "Loose.docset")))

    def test_notes_rejects_path_names(self):
        self.installed_foo()
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
            "source": "kapeli", "version": "1.0", "installed": "2026-11-14"}})
        code, out, err = self.main("remove", "Foo")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(os.path.join(self.store_dir, "Foo.docset")))
        self.assertTrue(os.path.isdir(os.path.join(target, "Foo.docset")))

    def test_remove_oserror_is_cli_error_7(self):
        self.installed_foo()
        with mock.patch.object(docset.shutil, "rmtree", side_effect=OSError("boom")):
            code, out, err = self.main("remove", "Foo")
        self.assertEqual(code, 7)
        self.assertIn("boom", err)


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
            self.assertIn("Py:1", [h["ref"] for h in hits])

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
