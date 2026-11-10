"""Tests for skills/pygameturbo: the vendored docs and refresh_references.py.

Offline: a fake fetcher stands in for GitHub. TestCommittedTree checks the
committed references against their manifest (catches hand edits) and that
SKILL.md routes to every vendored page.
Run from the repo root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("pygameturbo"):
    raise unittest.SkipTest("pygameturbo not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "pygameturbo")
REFS = os.path.join(SKILL_DIR, "references")

spec = importlib.util.spec_from_file_location(
    "pgt_refresh", os.path.join(SKILL_DIR, "scripts", "refresh_references.py"))
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

SHA = "a" * 40


def fake_get(pages=None, api_sha=SHA):
    """get(url, accept=None) -> text; every raw file is 'body of <path>\\r\\n'."""
    calls = []

    def get(url, accept=None):
        calls.append(url)
        if url.startswith("https://api.github.com/"):
            return api_sha
        path = url.split(f"/{SHA}/", 1)[1]
        if pages is not None and path in pages:
            return pages[path]
        return "﻿body of " + path + "\r\n"
    get.calls = calls
    return get


class TestScript(unittest.TestCase):
    def test_sha_ref_needs_no_api_call(self):
        get = fake_get()
        self.assertEqual(rr.resolve(SHA, get), SHA)
        self.assertEqual(get.calls, [])

    def test_branch_resolved_through_api(self):
        get = fake_get()
        self.assertEqual(rr.resolve("main", get), SHA)
        self.assertIn("/commits/main", get.calls[0])

    def test_bad_api_answer_is_an_error(self):
        with self.assertRaises(rr.FetchError):
            rr.resolve("main", fake_get(api_sha="not found"))

    def test_fetch_normalizes_bom_and_crlf(self):
        files = rr.fetch_all(SHA, fake_get())
        self.assertEqual(files["overview.rst"], "body of doc/overview.rst\n")
        self.assertEqual(set(files), {p + ".rst" for p in rr.PAGES} | {"COPYING"})

    def test_manifest_urls_and_hashes(self):
        files = rr.fetch_all(SHA, fake_get())
        m = rr.build_manifest(SHA, files)
        self.assertEqual(m["commit"], SHA)
        self.assertEqual(m["pages"]["references/actor.rst"]["url"],
                         "https://pgturbo.readthedocs.io/references/actor.html")
        self.assertIsNone(m["pages"]["COPYING"]["url"])
        self.assertEqual(m["pages"]["COPYING"]["sha256"], rr.sha256(files["COPYING"]))

    def test_write_then_check(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "references"))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(rr.main(["--ref", SHA], get=fake_get(), skill_dir=d), 0)
                self.assertEqual(rr.main(["--check"], get=fake_get(), skill_dir=d), 0)
            path = os.path.join(d, "references", "overview.rst")
            with open(path, "a", encoding="utf-8") as f:
                f.write("edit\n")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(rr.main(["--check"], get=fake_get(), skill_dir=d), 1)
            self.assertIn("edited: overview.rst", out.getvalue())

    def test_check_with_ref_reports_upstream_change(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "references"))
            with redirect_stdout(io.StringIO()):
                rr.main(["--ref", SHA], get=fake_get(), skill_dir=d)
            changed = fake_get(pages={"doc/overview.rst": "new text\n"})
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(rr.main(["--check", "--ref", SHA], get=changed, skill_dir=d), 1)
            self.assertIn("stale", out.getvalue())

    def test_network_error_exit_code(self):
        def broken(url, accept=None):
            raise rr.FetchError(url + ": down")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "references"))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(rr.main(["--ref", SHA], get=broken, skill_dir=d), 2)


class TestCommittedTree(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REFS, "manifest.json"), encoding="utf-8") as f:
            self.m = json.load(f)
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            self.skill = f.read()

    def test_files_match_manifest(self):
        self.assertEqual(rr.committed_problems(REFS), [])

    def test_manifest_lists_exactly_the_vendored_pages(self):
        self.assertEqual(set(self.m["pages"]), {p + ".rst" for p in rr.PAGES} | {"COPYING"})
        self.assertTrue(rr.is_sha(self.m["commit"]))
        self.assertIn("LGPL-3.0", self.m["license"])

    def test_skill_paths_exist(self):
        for path in re.findall(r"`(references/[^`<>* ]+)`", self.skill):
            path = path.rstrip(".")
            if "..." in path:
                continue
            self.assertTrue(os.path.exists(os.path.join(SKILL_DIR, path)), path)

    def test_skill_routes_every_topic_page(self):
        for page in rr.PAGES:
            section, _, name = page.rpartition("/")
            if section in ("deep_dives", "references"):
                # by topic name in a list, or by its full path
                self.assertTrue(f"`{name}`" in self.skill or f"references/{page}.rst" in self.skill, page)
            else:
                self.assertIn(name.split("_")[0], self.skill, page)


if __name__ == "__main__":
    unittest.main()
