"""Tests for skills/opencode-api: api_lookup.py (offline, fixture spec),
refresh_references.py (fake fetcher) and the committed openapi.json.
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

if not selected("opencode-api"):
    raise unittest.SkipTest("opencode-api not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "opencode-api")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SKILL_DIR, "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lookup = load("api_lookup")
refresh = load("refresh_references")

SPEC = {
    "openapi": "3.1.0", "info": {"title": "opencode HttpApi", "version": "0.0.1"},
    "tags": [{"name": "session"}, {"name": "server"}],
    "paths": {
        "/api/info": {"get": {"operationId": "server.info", "tags": ["server"], "summary": "Get server info",
                              "responses": {"200": {"description": "ok", "content": {"application/json": {
                                  "schema": {"$ref": "#/components/schemas/Info"}}}}}}},
        "/api/session": {
            "get": {"operationId": "session.list", "tags": ["session"], "summary": "List sessions",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "number"}},
                        {"name": "location", "in": "query", "style": "deepObject", "explode": True,
                         "schema": {"type": "object", "properties": {"directory": {"type": "string"}}}},
                    ]},
            "post": {"operationId": "session.create", "tags": ["session"], "summary": "Create a session",
                     "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/NewSession"}}}}}},
        "/api/session/{sessionID}/prompt": {"post": {
            "operationId": "session.prompt", "tags": ["session"], "summary": "Send a prompt",
            "parameters": [{"name": "sessionID", "in": "path", "required": True, "schema": {"type": "string"}}]}},
    },
    "components": {"schemas": {
        "Info": {"type": "object", "properties": {"url": {"type": "string"}}},
        "NewSession": {"type": "object", "properties": {"title": {"type": "string"},
                                                        "parent": {"$ref": "#/components/schemas/NewSession"}}},
    }},
}


class TestLookup(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = lookup.main(list(argv), spec=SPEC)
        return code, out.getvalue()

    def test_tags(self):
        code, out = self.run_main("--tags")
        self.assertEqual(code, 0)
        self.assertIn("session", out)
        self.assertIn("3", out)  # three session operations

    def test_list_by_tag_and_substring(self):
        _, out = self.run_main("--list", "session")
        self.assertIn("POST   /api/session  session.create", out)
        self.assertNotIn("server.info", out)
        _, out = self.run_main("--list", "prompt")
        self.assertIn("session.prompt", out)

    def test_op_by_id_and_by_method_path(self):
        for q in (["session.create"], ["POST", "/api/session"], ["post /api/session"]):
            code, out = self.run_main("--op", *q)
            self.assertEqual(code, 0, q)
            self.assertIn("session.create", out)
            self.assertIn('"title"', out)  # $ref resolved into the body schema
            self.assertIn("opencode api session.create", out)  # how to call it

    def test_op_shows_parameters(self):
        _, out = self.run_main("--op", "session.prompt")
        self.assertIn("sessionID", out)
        self.assertIn("path", out)

    def test_op_shows_style_and_deep_object_url(self):
        _, out = self.run_main("--op", "session.list")
        self.assertIn("location (query, style=deepObject, explode)", out)
        self.assertIn("in the URL: ?location[directory]=<directory>", out)
        curl = [line for line in out.splitlines() if line.startswith("curl: ")]
        self.assertEqual(len(curl), 1)
        # -g for the brackets; the deepObject parameter kept, the optional limit left out
        self.assertIn("curl -g -u opencode:$OPENCODE_PASSWORD", curl[0])
        self.assertIn("/api/session?location[directory]=<directory>", curl[0])
        self.assertNotIn("limit=", curl[0])
        self.assertNotIn("-X", curl[0])

    def test_curl_line_for_a_body_and_path_parameter(self):
        _, out = self.run_main("--op", "session.create")
        self.assertIn("curl: curl -u opencode:$OPENCODE_PASSWORD -X POST "
                      "-H 'content-type: application/json' -d '<json>' "
                      "\"http://127.0.0.1:<port>/api/session\"", out)
        _, out = self.run_main("--op", "session.prompt")
        self.assertIn("/api/session/{sessionID}/prompt\"", out)
        self.assertNotIn(" -g ", out)

    def test_query_example_forms(self):
        self.assertEqual(lookup.query_example({"name": "limit", "in": "query"}), "limit=<limit>")
        self.assertEqual(lookup.query_example({"name": "f", "in": "query", "style": "deepObject"}),
                         "f[<key>]=<value>")
        self.assertEqual(
            lookup.query_example({"name": "f", "in": "query", "style": "deepObject",
                                  "schema": {"properties": {"a": {}, "b": {}}}}),
            "f[a]=<a>&f[b]=<b>")
        self.assertEqual(lookup.param_flags({"in": "query", "style": "form", "explode": False}),
                         "query, style=form, no explode")

    def test_recursive_ref_does_not_loop(self):
        _, out = self.run_main("--schema", "NewSession")
        self.assertIn("NewSession", out)

    def test_grep(self):
        _, out = self.run_main("--grep", "server info")
        self.assertIn("server.info", out)

    def test_grep_names_the_matching_field(self):
        _, out = self.run_main("--grep", "info")
        line = [l for l in out.splitlines() if "server.info" in l][0]
        self.assertIn("[id, path, summary]", line)

    def test_unknown_op_exits_2(self):
        code, out = self.run_main("--op", "nope.nothing")
        self.assertEqual(code, 2)
        self.assertIn("Try --list", out)  # points to --list / --grep


class TestRefresh(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.body = json.dumps(SPEC)

    def fetch(self, body):
        tag = '"%s"' % hashlib.md5(body.encode()).hexdigest()
        return lambda url, etag: (304, None, etag) if etag == tag else (200, body, tag)

    def run_refresh(self, fetch, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            code = refresh.refresh(self.dir, fetch, **kw)
        return code, out.getvalue()

    def test_first_second_and_changed(self):
        self.assertEqual(self.run_refresh(self.fetch(self.body))[0], 0)
        code, out = self.run_refresh(self.fetch(self.body), check=True)
        self.assertEqual(code, 0, out)
        self.assertIn("unchanged", out)
        changed = json.dumps(dict(SPEC, info={"title": "x", "version": "0.0.2"}))
        self.assertEqual(self.run_refresh(self.fetch(changed), check=True)[0], 1)
        code, out = self.run_refresh(self.fetch(changed))
        self.assertIn("updated", out)
        with open(os.path.join(self.dir, "references", "openapi.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["info"]["version"], "0.0.2")

    def test_rejects_non_openapi(self):
        code, out = self.run_refresh(lambda url, etag: (200, "<html>nope</html>", None))
        self.assertEqual(code, 2)

    def test_hand_edit_is_restored(self):
        self.run_refresh(self.fetch(self.body))
        with open(os.path.join(self.dir, "references", "openapi.json"), "a") as f:
            f.write(" ")
        self.assertEqual(self.run_refresh(self.fetch(self.body), check=True)[0], 1)


class TestCommittedTree(unittest.TestCase):
    def test_spec_matches_manifest(self):
        refs = os.path.join(SKILL_DIR, "references")
        with open(os.path.join(refs, "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        with open(os.path.join(refs, "openapi.json"), encoding="utf-8", newline="") as f:
            text = f.read().replace("\r\n", "\n")
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), m["sha256"],
                         "openapi.json differs from the downloaded copy - never hand-edit references/")
        spec = json.loads(text)
        self.assertTrue(spec["openapi"].startswith("3."))
        self.assertTrue(all(p.startswith(("/api/", "/auth/")) for p in spec["paths"]))


if __name__ == "__main__":
    unittest.main()
