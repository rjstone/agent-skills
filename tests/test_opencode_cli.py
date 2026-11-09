"""Tests for skills/opencode-cli (CLI docs cache).

Its refresh script is opencode-build's with SECTION/BASE_URL for the CLI
section; the refresh logic itself is covered in test_opencode_build.py.
Here: the CLI constants, an offline round trip, and the committed tree.
Run from the repo root: python3 -m unittest discover -s tests -v
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("opencode-cli"):
    raise unittest.SkipTest("opencode-cli not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "opencode-cli")
spec = importlib.util.spec_from_file_location("cli_refresh", os.path.join(SKILL_DIR, "scripts", "refresh_references.py"))
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

INDEX = """## Build

- [Intro](https://opencode.ai/docs/build/)

## CLI

- [Intro](https://opencode.ai/docs/cli/)
- [Commands](https://opencode.ai/docs/cli/commands/)

## API
"""
PAGES = {"https://opencode.ai/docs/cli.md": "# Intro\n",
         "https://opencode.ai/docs/cli/commands.md": "# Commands\r\n"}


def fake(url, etag):
    if url == rr.INDEX_URL:
        return 200, INDEX, None
    body = PAGES[url]
    tag = '"%s"' % hashlib.md5(body.encode()).hexdigest()
    return (304, None, etag) if etag == tag else (200, body, tag)


class TestCliSection(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((rr.SECTION, rr.BASE_URL), ("CLI", "https://opencode.ai/docs/cli/"))

    def test_parse_and_names(self):
        urls = rr.parse_section(INDEX, "CLI")
        self.assertEqual(urls, ["https://opencode.ai/docs/cli/", "https://opencode.ai/docs/cli/commands/"])
        self.assertEqual([rr.page_file(u) for u in urls], ["intro.md", "commands.md"])
        self.assertEqual(rr.md_url(urls[0]), "https://opencode.ai/docs/cli.md")

    def test_round_trip(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rr.refresh(d, fake), 0)
            out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(rr.refresh(d, fake, check=True), 0)
        self.assertIn("unchanged: 2", out.getvalue())
        with open(os.path.join(d, "references", "commands.md"), newline="") as f:
            self.assertEqual(f.read(), "# Commands\n")  # stored LF


class TestCommittedTree(unittest.TestCase):
    def setUp(self):
        self.refs = os.path.join(SKILL_DIR, "references")
        with open(os.path.join(self.refs, "manifest.json"), encoding="utf-8") as f:
            self.m = json.load(f)

    def test_manifest_matches_files(self):
        self.assertEqual(sorted(n for n in os.listdir(self.refs) if n.endswith(".md")), sorted(self.m["pages"]))
        self.assertEqual(self.m["section"], "CLI")

    def test_hashes_match_lf_normalized_files(self):
        for name, e in self.m["pages"].items():
            with open(os.path.join(self.refs, name), encoding="utf-8", newline="") as f:
                text = rr.normalize(f.read())
            self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), e["sha256"],
                             f"{name} differs from the downloaded copy - never hand-edit references/")

    def test_errata_pages_exist(self):
        with open(os.path.join(SKILL_DIR, "ERRATA.md"), encoding="utf-8") as f:
            for name in rr.errata_ids(f.read()):
                self.assertIn(name, self.m["pages"])


if __name__ == "__main__":
    unittest.main()
