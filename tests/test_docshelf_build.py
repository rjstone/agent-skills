"""Offline tests for skills/docshelf-build. No network: inventories are made
by make_inv() and sites are folders or fake openers. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
import zlib
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("docshelf-build"):
    raise unittest.SkipTest("docshelf-build not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO_ROOT, "skills", "docshelf-build")
sys.path.insert(0, os.path.join(SKILL, "scripts"))

import build_core  # noqa: E402
from build_core import CLIError  # noqa: E402
from build_inventory import parse_inventory, page_key, split_uri  # noqa: E402


def make_inv(entries: List[Tuple[str, str, str, str, str]], project: str = "Demo",
             version: str = "1.0") -> bytes:
    """A Sphinx v2 inventory; entries are (name, role, priority, uri, dispname)."""
    head = ("# Sphinx inventory version 2\n# Project: %s\n# Version: %s\n"
            "# The remainder of this file is compressed using zlib.\n"
            % (project, version)).encode()
    body = "".join("%s %s %s %s %s\n" % e for e in entries).encode()
    return head + zlib.compress(body)


class InventoryTests(unittest.TestCase):
    def test_parse_expands_dollar_and_keeps_dash_dispname(self):
        hdr, es = parse_inventory(make_inv([("opt", "cmd:cmd", "1", "cmd/opt.html#$", "-")]))
        self.assertEqual(hdr, {"project": "Demo", "version": "1.0"})
        self.assertEqual(es[0].uri, "cmd/opt.html#opt")
        self.assertEqual(es[0].dispname, "-")
        self.assertEqual((es[0].role, es[0].priority), ("cmd:cmd", 1))

    def test_names_with_spaces(self):
        _, es = parse_inventory(make_inv([("my label", "std:label", "-1", "a.html#x", "My Label")]))
        self.assertEqual(es[0].name, "my label")
        self.assertEqual(es[0].priority, -1)
        self.assertEqual(es[0].dispname, "My Label")

    def test_name_with_a_number_word(self):
        # real Yosys entry: a bare "10" inside the name must not pass as the priority
        name = "cmd/x:intel alm (cyclone v, arria v, cyclone 10 gx)"
        _, es = parse_inventory(make_inv([(name, "std:label", "-1", "cmd/x.html#alm", "Intel ALM")]))
        self.assertEqual([(e.name, e.role) for e in es], [(name, "std:label")])

    def test_split_uri(self):
        self.assertEqual(split_uri("cmd/opt.html#opt"), ("cmd/opt.html", "opt"))
        self.assertEqual(split_uri("guide/a.html"), ("guide/a.html", None))

    def test_page_keys(self):
        self.assertEqual(page_key("cmd/opt.html"), "cmd/opt")
        self.assertEqual(page_key("api/foo/"), "api/foo")
        self.assertEqual(page_key(""), "index")
        self.assertEqual(page_key("index.html"), "index")

    def test_rejects_v1_and_garbage(self):
        for data in (b"# Sphinx inventory version 1\n# Project: x\n# Version: 1\nfoo mod foo.html\n",
                     b"<html>not found</html>"):
            with self.assertRaises(CLIError) as c:
                parse_inventory(data)
            self.assertEqual(c.exception.code, 3)

    def test_version_constant(self):
        self.assertRegex(build_core.VERSION, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
