"""Tests for skills/opencode-console (Console docs cache, prices redacted).

Its refresh script is opencode-build's with SECTION/BASE_URL for the CLI
section plus redact_prices(); the refresh logic itself is covered in
test_opencode_build.py. Here: constants, redaction, an offline round trip,
and the committed tree.
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

if not selected("opencode-console"):
    raise unittest.SkipTest("opencode-console not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "opencode-console")
spec = importlib.util.spec_from_file_location("console_refresh", os.path.join(SKILL_DIR, "scripts", "refresh_references.py"))
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

INDEX = """## Build

- [Intro](https://opencode.ai/docs/build/)

## Console

- [Intro](https://opencode.ai/docs/console/)

### API

- [Models](https://opencode.ai/docs/console/api/models/)

## API
"""
PAGES = {"https://opencode.ai/docs/console.md": "# Intro\n",
         "https://opencode.ai/docs/console/api/models.md": "# Models\r\nGo is $10/month; a $0 budget blocks spend.\r\n"}


def fake(url, etag):
    if url == rr.INDEX_URL:
        return 200, INDEX, None
    body = PAGES[url]
    tag = '"%s"' % hashlib.md5(body.encode()).hexdigest()
    return (304, None, etag) if etag == tag else (200, body, tag)


class TestConsoleSection(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((rr.SECTION, rr.BASE_URL), ("Console", "https://opencode.ai/docs/console/"))

    def test_parse_and_names(self):
        urls = rr.parse_section(INDEX, "Console")  # "### API" stays inside the section
        self.assertEqual(urls, ["https://opencode.ai/docs/console/", "https://opencode.ai/docs/console/api/models/"])
        self.assertEqual([rr.page_file(u) for u in urls], ["intro.md", "api-models.md"])
        self.assertEqual(rr.md_url(urls[0]), "https://opencode.ai/docs/console.md")

    def test_redact_prices(self):
        cases = {"$2.50 in": "[check-api] in", "$10/month": "[check-api]/month", "$1,000": "[check-api]",
                 "$0.042": "[check-api]", "4.6% + $0.31": "4.6% + [check-api]",
                 "a `$0` budget": "a `$0` budget", "$0.": "$0.", "$HOME and $": "$HOME and $"}
        for src, want in cases.items():
            self.assertEqual(rr.redact_prices(src), want, src)

    def test_round_trip(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rr.refresh(d, fake), 0)
            out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(rr.refresh(d, fake, check=True), 0)
        self.assertIn("unchanged: 2", out.getvalue())
        with open(os.path.join(d, "references", "api-models.md"), newline="") as f:
            self.assertEqual(f.read(), "# Models\nGo is [check-api]/month; a $0 budget blocks spend.\n")


class TestCommittedTree(unittest.TestCase):
    def setUp(self):
        self.refs = os.path.join(SKILL_DIR, "references")
        with open(os.path.join(self.refs, "manifest.json"), encoding="utf-8") as f:
            self.m = json.load(f)

    def test_manifest_matches_files(self):
        self.assertEqual(sorted(n for n in os.listdir(self.refs) if n.endswith(".md")), sorted(self.m["pages"]))
        self.assertEqual(self.m["section"], "Console")

    def test_hashes_match_lf_normalized_files(self):
        for name, e in self.m["pages"].items():
            with open(os.path.join(self.refs, name), encoding="utf-8", newline="") as f:
                text = rr.normalize(f.read())
            self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), e["sha256"],
                             f"{name} differs from the downloaded copy - never hand-edit references/")

    def test_no_prices_left(self):
        for name in self.m["pages"]:
            with open(os.path.join(self.refs, name), encoding="utf-8") as f:
                self.assertEqual(rr.PRICE_RE.findall(f.read()), [], name)

    def test_skill_md_names_existing_pages(self):
        import re
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            names = set(re.findall(r"references/([a-z-]+\.md)", f.read()))
        self.assertTrue(names)
        for n in names:
            self.assertIn(n, self.m["pages"])


if __name__ == "__main__":
    unittest.main()
