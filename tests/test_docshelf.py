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
                 alias: Optional[str] = None, mtime: int = 1700000000) -> str:
    """Write <cache>/devdocs/<slug>/{index.json, db.json, meta.json} and append
    the manifest row to <cache>/devdocs/docs.json; return the docset folder.

    entries are (name, type, path) tuples; pages maps path -> HTML."""
    root = os.path.join(cache, "devdocs")
    folder = os.path.join(root, slug)
    os.makedirs(folder, exist_ok=True)
    types = sorted({t for _, t, _ in entries})
    index = {"entries": [{"name": n, "type": t, "path": p} for n, t, p in entries],
             "types": [{"name": t, "count": sum(1 for e in entries if e[1] == t)}
                       for t in types]}
    with open(os.path.join(folder, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f)
    with open(os.path.join(folder, "db.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f)
    meta = {"slug": slug, "name": name, "release": release, "mtime": mtime}
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    manifest_path = os.path.join(root, "docs.json")
    manifest = []
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    row = {"name": name, "slug": slug, "release": release, "mtime": mtime,
           "type": slug.split("~")[0]}
    if alias:
        row["alias"] = alias
    manifest.append(row)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
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


if __name__ == "__main__":
    unittest.main()
