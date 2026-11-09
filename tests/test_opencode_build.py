"""Tests for skills/opencode-build/scripts/refresh_references.py.

Offline: a fixture llms.txt and a fake fetcher stand in for the network.
TestCommittedTree checks the committed references against their manifest
(catches hand edits). Run from the repo root: python3 -m unittest discover -s tests -v
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("opencode-build"):
    raise unittest.SkipTest("opencode-build not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "opencode-build")
SCRIPT = os.path.join(SKILL_DIR, "scripts", "refresh_references.py")

spec = importlib.util.spec_from_file_location("refresh_references", SCRIPT)
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

INDEX = """# OpenCode docs

## CLI

- [Plugins](https://opencode.ai/docs/cli/plugins/)

## Build

- [Intro](https://opencode.ai/docs/build/)

### Plugins

- [Overview](https://opencode.ai/docs/build/plugins/)
- [Server](https://opencode.ai/docs/build/plugins/server/)

## API

- [Server](https://opencode.ai/docs/api/server/)
"""

ERRATA = """# Errata

## E01: wrong export key
- Page: `plugins-server.md`
- Says: x
- Actually: y

## E02: other
- Page: `plugins.md`
"""


class FakeWeb:
    """fetch(url, etag) -> (status, body, etag). Pages: md_url -> body."""

    def __init__(self, index, pages):
        self.index, self.pages, self.calls = index, dict(pages), []

    def tag(self, body):
        return '"%s"' % hashlib.md5(body.encode()).hexdigest()

    def __call__(self, url, etag):
        self.calls.append((url, etag))
        if url == rr.INDEX_URL:
            return 200, self.index, None
        if url not in self.pages:
            raise rr.FetchError(url, "404")
        body = self.pages[url]
        if etag is not None and etag == self.tag(body):
            return 304, None, etag
        return 200, body, self.tag(body)


PAGES = {
    "https://opencode.ai/docs/build.md": "# Intro\n",
    "https://opencode.ai/docs/build/plugins.md": "# Overview\n",
    "https://opencode.ai/docs/build/plugins/server.md": "# Server\n",
}


class TestPure(unittest.TestCase):
    def test_parse_section_stops_at_next_h2(self):
        self.assertEqual(rr.parse_section(INDEX, "Build"), [
            "https://opencode.ai/docs/build/",
            "https://opencode.ai/docs/build/plugins/",
            "https://opencode.ai/docs/build/plugins/server/",
        ])

    def test_parse_section_missing(self):
        self.assertEqual(rr.parse_section(INDEX, "Console"), [])

    def test_md_url(self):
        self.assertEqual(rr.md_url("https://opencode.ai/docs/build/plugins/server/"),
                         "https://opencode.ai/docs/build/plugins/server.md")
        self.assertEqual(rr.md_url("https://opencode.ai/docs/build/"),
                         "https://opencode.ai/docs/build.md")

    def test_page_file(self):
        self.assertEqual(rr.page_file("https://opencode.ai/docs/build/"), "intro.md")
        self.assertEqual(rr.page_file("https://opencode.ai/docs/build/plugins/"), "plugins.md")
        self.assertEqual(rr.page_file("https://opencode.ai/docs/build/plugins/effect/rpc/"),
                         "plugins-effect-rpc.md")

    def test_normalize(self):
        self.assertEqual(rr.normalize("a\r\nb\rc\n"), "a\nb\nc\n")

    def test_errata_ids(self):
        self.assertEqual(rr.errata_ids(ERRATA),
                         {"plugins-server.md": ["E01"], "plugins.md": ["E02"]})

    def test_errata_ids_ignore_fenced_examples(self):
        text = "```\n## E01: example\n- Page: `plugins-server.md`\n```\n" + ERRATA.replace("E01", "E07")
        self.assertEqual(rr.errata_ids(text),
                         {"plugins-server.md": ["E07"], "plugins.md": ["E02"]})


class TestRefresh(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.refs = os.path.join(self.dir, "references")
        with open(os.path.join(self.dir, "ERRATA.md"), "w") as f:
            f.write(ERRATA)

    def run_refresh(self, web, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rr.refresh(self.dir, web, **kw)
        return code, out.getvalue()

    def read(self, name):
        with open(os.path.join(self.refs, name), newline="") as f:
            return f.read()

    def manifest(self):
        with open(os.path.join(self.refs, "manifest.json")) as f:
            return json.load(f)

    def test_first_run_downloads_everything(self):
        code, out = self.run_refresh(FakeWeb(INDEX, PAGES))
        self.assertEqual(code, 0)
        self.assertEqual(self.read("plugins-server.md"), "# Server\n")
        m = self.manifest()
        self.assertEqual(sorted(m["pages"]), ["intro.md", "plugins-server.md", "plugins.md"])
        e = m["pages"]["plugins-server.md"]
        self.assertEqual(e["url"], "https://opencode.ai/docs/build/plugins/server/")
        self.assertEqual(e["sha256"], hashlib.sha256(b"# Server\n").hexdigest())
        self.assertIn("new: 3", out)

    def test_second_run_is_all_304(self):
        self.run_refresh(FakeWeb(INDEX, PAGES))
        web = FakeWeb(INDEX, PAGES)
        before = self.manifest()
        code, out = self.run_refresh(web)
        self.assertEqual(code, 0)
        self.assertIn("unchanged: 3", out)
        self.assertTrue(all(etag for url, etag in web.calls[1:]))
        self.assertEqual(self.manifest(), before)  # stable: no churn

    def test_force_skips_etag(self):
        self.run_refresh(FakeWeb(INDEX, PAGES))
        web = FakeWeb(INDEX, PAGES)
        self.run_refresh(web, force=True)
        self.assertTrue(all(etag is None for url, etag in web.calls))

    def test_changed_page_is_written_and_errata_flagged(self):
        self.run_refresh(FakeWeb(INDEX, PAGES))
        pages = dict(PAGES)
        pages["https://opencode.ai/docs/build/plugins/server.md"] = "# Server v2\n"
        code, out = self.run_refresh(FakeWeb(INDEX, pages))
        self.assertEqual(code, 0)
        self.assertEqual(self.read("plugins-server.md"), "# Server v2\n")
        self.assertIn("updated: 1", out)
        self.assertIn("re-check errata", out)
        self.assertIn("E01", out)
        self.assertNotIn("E02", out)

    def test_crlf_body_is_stored_lf_and_same_hash(self):
        pages = dict(PAGES)
        pages["https://opencode.ai/docs/build.md"] = "# Intro\r\nx\r\n"
        self.run_refresh(FakeWeb(INDEX, pages))
        self.assertEqual(self.read("intro.md"), "# Intro\nx\n")

    def test_crlf_checkout_is_not_a_change(self):
        self.run_refresh(FakeWeb(INDEX, PAGES))
        # Windows checkout: same content with CRLF on disk; server ETag changed
        with open(os.path.join(self.refs, "plugins.md"), "w", newline="") as f:
            f.write("# Overview\r\n")
        m = self.manifest()
        m["pages"]["plugins.md"]["etag"] = '"stale"'
        with open(os.path.join(self.refs, "manifest.json"), "w") as f:
            json.dump(m, f)
        code, out = self.run_refresh(FakeWeb(INDEX, PAGES), check=True)
        self.assertEqual(code, 0, out)

    def test_hand_edited_file_is_restored_despite_304(self):
        self.run_refresh(FakeWeb(INDEX, PAGES))
        with open(os.path.join(self.refs, "plugins.md"), "a") as f:
            f.write("hand edit\n")
        self.assertEqual(self.run_refresh(FakeWeb(INDEX, PAGES), check=True)[0], 1)
        code, out = self.run_refresh(FakeWeb(INDEX, PAGES))
        self.assertEqual(self.read("plugins.md"), "# Overview\n")
        self.assertIn("updated: 1", out)

    def test_removed_page_kept_unless_prune(self):
        self.run_refresh(FakeWeb(INDEX, PAGES))
        index = INDEX.replace("- [Server](https://opencode.ai/docs/build/plugins/server/)\n", "")
        code, out = self.run_refresh(FakeWeb(index, PAGES))
        self.assertIn("removed: 1", out)
        self.assertTrue(os.path.exists(os.path.join(self.refs, "plugins-server.md")))
        self.run_refresh(FakeWeb(index, PAGES), prune=True)
        self.assertFalse(os.path.exists(os.path.join(self.refs, "plugins-server.md")))
        self.assertNotIn("plugins-server.md", self.manifest()["pages"])

    def test_check_mode(self):
        code, _ = self.run_refresh(FakeWeb(INDEX, PAGES), check=True)
        self.assertEqual(code, 1)  # nothing downloaded yet
        self.assertFalse(os.path.exists(self.refs))  # no writes
        self.run_refresh(FakeWeb(INDEX, PAGES))
        self.assertEqual(self.run_refresh(FakeWeb(INDEX, PAGES), check=True)[0], 0)
        pages = dict(PAGES)
        pages["https://opencode.ai/docs/build/plugins.md"] = "# changed\n"
        before = self.read("plugins.md")
        self.assertEqual(self.run_refresh(FakeWeb(INDEX, pages), check=True)[0], 1)
        self.assertEqual(self.read("plugins.md"), before)

    def test_network_error_exits_2(self):
        pages = dict(PAGES)
        del pages["https://opencode.ai/docs/build/plugins.md"]
        code, out = self.run_refresh(FakeWeb(INDEX, pages))
        self.assertEqual(code, 2)
        self.assertIn("https://opencode.ai/docs/build/plugins.md", out)

    def test_missing_section_exits_2(self):
        code, out = self.run_refresh(FakeWeb("# nothing\n", PAGES))
        self.assertEqual(code, 2)


@unittest.skipUnless(os.path.isdir(os.path.join(SKILL_DIR, "references")), "no references yet")
class TestCommittedTree(unittest.TestCase):
    """Integrity of the committed skill: catches hand edits and broken links."""

    def setUp(self):
        self.refs = os.path.join(SKILL_DIR, "references")
        with open(os.path.join(self.refs, "manifest.json"), encoding="utf-8") as f:
            self.m = json.load(f)

    def md_files(self):
        """Downloaded pages only; `*.local.md` are hand-written additions."""
        return sorted(n for n in os.listdir(self.refs)
                      if n.endswith(".md") and not n.endswith(".local.md"))

    def local_files(self):
        return sorted(n for n in os.listdir(self.refs) if n.endswith(".local.md"))

    def test_manifest_matches_files(self):
        self.assertEqual(self.md_files(), sorted(self.m["pages"]))

    def test_local_files_supplement_a_downloaded_page(self):
        for name in self.local_files():
            page = name[: -len(".local.md")] + ".md"
            self.assertIn(page, self.m["pages"],
                          f"{name} has no downloaded {page} to supplement")

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


def load_script(name):
    path = os.path.join(SKILL_DIR, "scripts", name + ".py")
    s = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return mod


co = load_script("client_outline")
dd = load_script("dts_decls")

# Shaped like tsc's emit for @opencode/client dist/promise/client.d.ts
CLIENT_DTS = """export * as OpenCode from "./client.js";
export type { ClientOptions, RequestOptions } from "./generated/client.js";
export declare function make(options: ClientOptions): {
    agent: {
        list: (input?: import("./index.js").AgentListInput, requestOptions?: OpenCode.RequestOptions) => Promise<import("./index.js").AgentListOutput>;
    };
    experimental: {
        generate: {
            text: (input: import("./index.js").GenerateTextInput, requestOptions?: OpenCode.RequestOptions) => Promise<{
                text: string;
            }>;
        };
    };
    event: {
        subscribe<Type extends "a" | "b">(options?: X<Type>): AsyncIterable<Y>;
    };
};
export declare function other(): void;
"""

API_DTS = """import type { OpenCode } from "./client.js";
type Client = ReturnType<typeof OpenCode.make>;
export type AgentApi = Client["agent"];
export type ExperimentalSessionApi = Client["experimental"]["session"];
"""

PLUGIN_DTS = """import type { X } from "./x.js";
export interface AgentDomain extends AgentApi {
    readonly transform: Transform<import("./agent.js").AgentEditor>;
}
export interface RpcDomain extends RpcApi<Pick<O, "signal"> & {
    readonly headers?: never;
}> {
    readonly register: () => Promise<void>;
}
export interface EmptyDomain {}
export type SessionDomain = Pick<SessionApi, "list"> & {
    readonly hook: (callback: (input: {
        readonly a: string;
    }) => void) => Promise<void>;
};
export type OneLineDomain = Pick<A, "b">;
export interface DomainHelper {
    readonly x: string;
}
export interface AgentDomainExtra {
}
"""


class TestClientOutline(unittest.TestCase):
    def test_methods_groups_and_qualifiers(self):
        lines, bad = co.outline(CLIENT_DTS)
        self.assertEqual(lines[0], "interface OpenCodeClient {")
        self.assertIn("    agent: {", lines)
        self.assertIn("        list(input?: AgentListInput, requestOptions?: RequestOptions)"
                      ": Promise<AgentListOutput>", lines)
        self.assertEqual(lines[-1], "}")
        self.assertNotIn("other", "\n".join(lines))

    def test_inline_return_type_folded(self):
        lines, _ = co.outline(CLIENT_DTS)
        self.assertIn("            text(input: GenerateTextInput, requestOptions?: RequestOptions)"
                      ": Promise<{ text: string }>", lines)

    def test_unclassified_kept_and_reported(self):
        lines, bad = co.outline(CLIENT_DTS)
        self.assertEqual([b.strip()[:9] for b in bad], ["subscribe"])
        self.assertTrue(any(l.strip().startswith("subscribe<") for l in lines))

    def test_long_line_replaced_by_comment(self):
        lines, _ = co.outline(CLIENT_DTS, max_line=60)
        self.assertIn("        // subscribe: signature over 60 characters, see client.d.ts", lines)

    def test_missing_make_raises(self):
        with self.assertRaises(ValueError):
            co.outline("export declare function other(): void;\n")

    def test_aliases(self):
        self.assertEqual(co.aliases(API_DTS), [
            'type AgentApi = OpenCodeClient["agent"]',
            'type ExperimentalSessionApi = OpenCodeClient["experimental"]["session"]',
        ])


class TestDtsDecls(unittest.TestCase):
    def test_default_pattern_finds_whole_name_matches_only(self):
        names = [n for n, _ in dd.declarations(PLUGIN_DTS)]
        self.assertEqual(names, ["AgentDomain", "RpcDomain", "EmptyDomain",
                                 "SessionDomain", "OneLineDomain"])

    def test_interface_with_braces_in_extends_ends_at_closing_line(self):
        text = dict(dd.declarations(PLUGIN_DTS))["RpcDomain"]
        self.assertTrue(text.startswith("export interface RpcDomain extends"))
        self.assertTrue(text.endswith("register: () => Promise<void>;\n}"))

    def test_multiline_type_alias_ends_when_balanced(self):
        text = dict(dd.declarations(PLUGIN_DTS))["SessionDomain"]
        self.assertTrue(text.endswith("}) => void) => Promise<void>;\n};"))
        self.assertEqual(dict(dd.declarations(PLUGIN_DTS))["OneLineDomain"],
                         'export type OneLineDomain = Pick<A, "b">;')

    def test_single_line_interface_and_qualifiers(self):
        found = dict(dd.declarations(PLUGIN_DTS))
        self.assertEqual(found["EmptyDomain"], "export interface EmptyDomain {}")
        self.assertIn("Transform<AgentEditor>", found["AgentDomain"])

    def test_custom_names(self):
        self.assertEqual([n for n, _ in dd.declarations(PLUGIN_DTS, "DomainHelper")],
                         ["DomainHelper"])

    def test_main_reads_folder(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "agent.d.ts"), "w", encoding="utf-8") as f:
                f.write(PLUGIN_DTS)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(dd.main([d, "--names", "OneLineDomain"]), 0)
            self.assertEqual(out.getvalue(),
                             '// agent.d.ts\nexport type OneLineDomain = Pick<A, "b">;\n\n')
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(dd.main([d, "--names", "Nope"]), 1)


if __name__ == "__main__":
    unittest.main()
