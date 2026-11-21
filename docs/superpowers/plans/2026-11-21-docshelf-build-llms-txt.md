# docshelf-build 0.2.0: llms.txt sites - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docshelf_build.py plan|build` accept an `llms.txt` (or sub-index) URL or local `.txt` file and build the same docvol files as the Sphinx path, fetching every listed page, keeping raw downloads in a page cache and recording per-page signals in the plan.

**Architecture:** Two new stdlib modules: `build_llms.py` (index parsing, page keys, the index tree) and `build_markdown.py` (Markdown/MDX to HTML, front matter, signals). Existing modules gain an llms branch: `build_fetch` (per-host robots, `.md` retry, page cache), `build_plan` (llms plan, `model:` rule for both kinds, llms summary), `build_html`/`build_docvol` (absolute-URL link rewriting, heading entries, `source_kind`), and `docshelf_build` (dispatch, `--refetch`, re-plan on index change).

**Tech Stack:** Python 3 standard library only; `unittest`; no network in tests (fake openers as in `tests/test_docshelf_build.py`).

**Spec:** `docs/superpowers/specs/2026-11-21-docshelf-build-llms-txt-design.md` (read it with this plan; earlier design: `docs/superpowers/specs/2026-11-21-docshelf-build-design.md`).

## Global Constraints

- Standard library only; no new dependencies; no network in tests.
- `metadata.version` in `skills/docshelf-build/SKILL.md` and `build_core.VERSION` both become `"0.2.0"` (Task 7); tests read `build_core.VERSION`, never a literal.
- Docvol `"format"` stays `1` (`DOCVOL_FORMAT`); `meta.json` gains `"source_kind": "llms"` (docshelf reads meta keys with `.get`, checked in `shelf_devdocs.py`, so unknown keys are ignored).
- Plans: `"kind": "llms"` for llms plans, `"kind": "sphinx"` for new Sphinx plans; a plan without `kind` is Sphinx.
- Every listed page starts `keep: "full"`, `why: "llms: all"`; plan `"rule": "llms-all"`.
- Fetch politeness reused from 0.1.0: User-Agent `docshelf-build/<VERSION>`, robots.txt, retries `RETRY_DELAYS`, 1 worker default (max 4), 0.5 s delay.
- Sub-index recursion depth limit 3; each index fetched once; only same-host sub-indexes followed.
- Over 300 full pages: warn and suggest narrowing; never refuse.
- Page cache: `<cache>/built-src/<name>/<key>.md|.html` plus `manifest.json` `{key: {url, sha256, fetched, type}}`, written atomically per file.
- Public repo rules (AGENTS.md): no account names, hostnames of private machines, absolute paths starting `/` in committed files except made-up test fixture paths. Test fixture URLs use `https://x.io/...` and `https://other.io/...`.
- Run tests from the repo root: `python3 -m unittest discover -s tests -p test_docshelf_build.py -v` (add `-k <ClassName>` for one class).

## Review Focus

1. **Hostile or odd URL paths in an index** (`../../etc/x.md`, `%2e%2e/`, query strings, `//double//slashes`): the page key never escapes the page cache or docvol folder; `..` segments are dropped, query and fragment are ignored. Tests in Task 1 (`url_key`) and Task 4 (`PageCache.put` refuses a key resolving outside its root).
2. **SOURCE that is not an llms.txt** (an HTML 404 page served with 200, or a file with no links): `plan` fails with `CLIError` code 3 ("no page links in ..."), writes no plan. Test in Task 1 and Task 7.
3. **Broken Markdown** (unterminated fence, unclosed `<Note>`, a component tag spanning lines): the rest of the page is still output (fence runs to end of page as code; unclosed component's text kept). Tests in Task 2.
4. **Index encoding quirks** (UTF-8 BOM, CRLF line ends, non-UTF-8 bytes): parsed like plain LF UTF-8, undecodable bytes replaced. Test in Task 1.
5. **Sub-index cycles and duplicates** (a.txt links b.txt links a.txt; a page listed in two sub-indexes): each index read once, page kept at its first occurrence, no infinite loop. Test in Task 1.

---

## File map

| File | Responsibility |
|---|---|
| `skills/docshelf-build/scripts/build_llms.py` (new) | parse one index, URL -> page key, read the index tree |
| `skills/docshelf-build/scripts/build_markdown.py` (new) | front matter, Markdown/MDX -> HTML, page signals |
| `skills/docshelf-build/scripts/build_fetch.py` | per-host robots, `Source.get_url`, `.md` retry, `PageCache`, `fetch_llms` |
| `skills/docshelf-build/scripts/build_plan.py` | `model:` rule (both kinds), `kind`, `make_llms_plan`, `summarize_llms` |
| `skills/docshelf-build/scripts/build_html.py` | `headings`, `rewrite_url_links` |
| `skills/docshelf-build/scripts/build_docvol.py` | shared writer, `write_llms_docvol`, `source_kind` |
| `skills/docshelf-build/scripts/build_core.py` | `VERSION = "0.2.0"`, `src_dir` |
| `skills/docshelf-build/scripts/docshelf_build.py` | dispatch by source kind, `--refetch`, `--base-url` check, re-plan, `remove` deletes page cache |
| `skills/docshelf-build/SKILL.md` | description + short llms.txt usage, version |
| `tests/test_docshelf_build.py` | all new tests (new classes `LlmsIndexTests`, `MarkdownTests`, `SignalsTests`, `LlmsFetchTests`, `LlmsPlanTests`, `LlmsDocvolTests`, `LlmsCliTests`) |
| `AGENTS.md`, `TODO.md` | skill entry; 8.9 done, classifier item added |

---

### Task 1: Index parsing, page keys, index tree (`build_llms.py`)

**Files:**
- Create: `skills/docshelf-build/scripts/build_llms.py`
- Test: `tests/test_docshelf_build.py` (class `LlmsIndexTests`)

**Interfaces:**
- Consumes: `build_core.CLIError`.
- Produces:
  - `Link = NamedTuple("Link", title: str, url: str, note: Optional[str], section: Optional[str])`
  - `parse_index(text: str, index_url: str) -> Tuple[str, List[Link]]`: `(H1 title or "", links)`; URLs made absolute against `index_url`; BOM and `\r` stripped.
  - `is_llms_source(arg: str) -> bool`: URL (http/https) whose path ends `.txt`, or an existing local file ending `.txt`.
  - `url_key(url: str, main_host: str) -> str`: the spec's key rules.
  - `LlmsPage = NamedTuple("LlmsPage", key: str, url: str, title: str, section: Optional[str], description: Optional[str])`
  - `Tree = NamedTuple("Tree", title: str, main_host: str, pages: List[LlmsPage], indexes: List[dict], sha256: str)`; each `indexes` item `{"url", "title", "pages": int|None, "parent": str|None, "note": str|None}` (`pages` None with `note` "other host, not followed" or "depth limit" for skipped sub-indexes).
  - `read_tree(source: str, get_text: Callable[[str], str], read_file: Callable[[str], str] = <open utf-8 replace>) -> Tree`: raises `CLIError(..., 3)` when the tree has no page links.

- [ ] **Step 1: Write the failing tests**

```python
FLAT_INDEX = """﻿# OpenCode\r
\r
> Agents in your terminal.\r
\r
- [Home](https://x.io/index.md)\r
\r
## Docs\r
\r
- [Build](https://x.io/docs/build.md): build agents\r
* [Run](/docs/run/)\r
  - [Run flags](docs/run/flags.mdx)\r
\r
## Optional\r
\r
- [Pricing](https://x.io/pricing)\r
- [Build again](https://x.io/docs/build.md)\r
"""

class LlmsIndexTests(unittest.TestCase):
    def test_parse_flat_index(self):
        title, links = parse_index(FLAT_INDEX, "https://x.io/llms.txt")
        self.assertEqual(title, "OpenCode")
        self.assertEqual([(l.title, l.url, l.note, l.section) for l in links], [
            ("Home", "https://x.io/index.md", None, None),
            ("Build", "https://x.io/docs/build.md", "build agents", "Docs"),
            ("Run", "https://x.io/docs/run/", None, "Docs"),
            ("Run flags", "https://x.io/docs/run/flags.mdx", None, "Docs"),
            ("Pricing", "https://x.io/pricing", None, "Optional"),
            ("Build again", "https://x.io/docs/build.md", None, "Optional")])  # dedup is read_tree's job

    def test_url_key(self):
        h = "x.io"
        for url, key in [("https://x.io/docs/build.md", "docs/build"),
                         ("https://x.io/docs/run/", "docs/run/index"),
                         ("https://x.io/", "index"),
                         ("https://x.io/a/b.mdx?x=1#frag", "a/b"),
                         ("https://x.io/a/page.html", "a/page"),
                         ("https://other.io/docs/a.md", "other.io/docs/a"),
                         ("https://x.io/../../etc/passwd.md", "etc/passwd"),
                         ("https://x.io/a/%2e%2e/%2e%2e/b.md", "b"),
                         ("https://x.io//a//b.md", "a/b")]:
            self.assertEqual(url_key(url, h), key, url)

    def test_is_llms_source(self):
        self.assertTrue(is_llms_source("https://x.io/llms.txt"))
        self.assertTrue(is_llms_source("https://x.io/_llms/python.txt"))
        self.assertFalse(is_llms_source("https://x.io/docs/"))
        # local: a real .txt file only (write one in a temp dir); a folder is Sphinx

    def test_tree_flat(self):
        tree = read_tree("https://x.io/llms.txt", get_text={"https://x.io/llms.txt": FLAT_INDEX}.__getitem__)
        self.assertEqual(tree.title, "OpenCode")
        self.assertEqual(tree.main_host, "x.io")
        self.assertEqual([p.key for p in tree.pages],
                         ["index", "docs/build", "docs/run/index", "docs/run/flags", "pricing"])
        self.assertEqual(tree.pages[1].description, "build agents")
        self.assertEqual(tree.indexes, [{"url": "https://x.io/llms.txt", "title": "OpenCode",
                                         "pages": 5, "parent": None, "note": None}])
        self.assertEqual(tree.sha256, hashlib.sha256(FLAT_INDEX.encode()).hexdigest())

    def test_tree_nested_cycle_dup_other_host(self):
        texts = {
            "https://x.io/llms.txt": "# Root\n## Python\n- [Py](/_llms/python.txt)\n"
                                     "- [Ext](https://other.io/llms.txt)\n- [Top](/top.md)\n",
            "https://x.io/_llms/python.txt": "# Python docs\n- [A](/py/a.md)\n- [Top](/top.md)\n"
                                             "- [Back](/llms.txt)\n- [Deeper](/_llms/d1.txt)\n",
            "https://x.io/_llms/d1.txt": "# D1\n- [D](/d/1.md)\n- [D2](/_llms/d2.txt)\n",
            "https://x.io/_llms/d2.txt": "# D2\n- [E](/d/2.md)\n- [D3](/_llms/d3.txt)\n",
        }
        tree = read_tree("https://x.io/llms.txt", texts.__getitem__)
        self.assertEqual([(p.key, p.section) for p in tree.pages],
                         [("py/a", "Python / Python docs"), ("top", "Python / Python docs"),
                          ("d/1", "Python / Python docs / D1"), ("d/2", "Python / Python docs / D1 / D2")])
        notes = {i["url"]: i["note"] for i in tree.indexes}
        self.assertEqual(notes["https://other.io/llms.txt"], "other host, not followed")
        self.assertEqual(notes["https://x.io/_llms/d3.txt"], "depth limit")
        self.assertEqual(sum(1 for i in tree.indexes if i["url"] == "https://x.io/llms.txt"), 1)

    def test_tree_local_file_main_host_by_majority(self):
        # local .txt with 2 links on x.io and 1 on other.io -> main_host "x.io",
        # other page key "other.io/..."

    def test_tree_without_links_is_error(self):
        with self.assertRaises(CLIError) as cm:
            read_tree("https://x.io/llms.txt", lambda u: "<!doctype html><html><body>Not found</body></html>")
        self.assertEqual(cm.exception.code, 3)
```

(Add `import hashlib` to the test file's imports. Write `test_tree_local_file_main_host_by_majority` fully, with a temp file and assertions on `main_host` and keys; add `"https://x.io/docs/build.md"` + `"https://x.io/docs/build.mdx"` in one index and assert keys `docs/build`, `docs/build-2`.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k LlmsIndexTests -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'build_llms'`.

- [ ] **Step 3: Implement `build_llms.py`**

- `parse_index`: line-based. H1 = first `# ` line. `## ` sets section (stripped text). Any line matching `^\s*[-*+]\s+\[(title)\]\((url)\)(\s*:\s*(note))?` is a link; title may contain `` `code` `` and nested `[..]` one level deep; URL may contain balanced `( )`. Decode/strip happen in `read_tree`/callers; `parse_index` itself strips a leading `﻿` and `\r`.
- `url_key`: `urlsplit`, ignore query/fragment, `unquote` the path, split on `/`, drop empty, `.` and `..` segments; trailing `/` (or empty path) appends `index`; strip one of `.md .mdx .html .htm` from the last segment; prefix `<host>/` when `host != main_host`.
- `read_tree`: depth-first in listing order, root depth 0, follow `.txt` same-host links while depth < 3 (a sub-index at depth 3 is recorded with `note: "depth limit"`). Section for pages of a sub-index = `" / ".join(x for x in (parent_section, sub_title) if x)` where `sub_title` = the sub-index's H1, else its link text. Dedup pages by URL (first wins), then assign keys; key collision -> `-2`, `-3` in listing order and `warn(...)`. `sha256` over the raw text bytes (UTF-8 encoded) of every index read, concatenated in visit order. A local root: `read_file(path)`, `main_host` = most common host among its page links (ties: first seen), index `url` = the path as given. Root fetch failure surfaces from `get_text` (it raises `CLIError` code 4, Task 4).

- [ ] **Step 4: Run tests to verify they pass**

Run: same command. Expected: all `LlmsIndexTests` pass; then the whole file passes.

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build/scripts/build_llms.py tests/test_docshelf_build.py
git commit -m "docshelf-build: parse llms.txt indexes and page keys"
```

---

### Task 2: Markdown/MDX to HTML (`build_markdown.py`)

**Files:**
- Create: `skills/docshelf-build/scripts/build_markdown.py`
- Test: `tests/test_docshelf_build.py` (class `MarkdownTests`)

**Interfaces:**
- Consumes: `build_html._serialize`, `build_html._tokens` (final pass: drops script/style/form/iframe, images -> alt).
- Produces:
  - `front_matter(text: str) -> Tuple[dict, str]`: (`{"title": ..., "description": ...}` with only keys present, simple `key: value` lines, quotes stripped; the body without the block).
  - `md_to_html(text: str) -> str`: body HTML (front matter dropped), passed through `_serialize(_tokens(...))`.
  - `slugify(text: str) -> str`: GitHub-style: lowercase, drop chars other than letters, digits, `-`, `_`, space; spaces -> `-`. Uniqueness per page (`x`, `x-1`, `x-2`) is handled inside `md_to_html`. (Decision: GitHub-style ids satisfy `anchor_id`'s no-whitespace rule and match `#anchors` that pages write for the live site.)

- [ ] **Step 1: Write the failing tests**

One test per row; each asserts `md_to_html(src)` equals (or, where noted, contains) the HTML. Whitespace between block tags: none (blocks are joined with `"\n"`; compare after `re.sub(r">\s+<", "><", html)` via a helper `norm()`).

| test | source | expected (normalized) |
|---|---|---|
| `test_headings_ids_unique` | `# A b\n## A b\nSetext\n===\n### C?` | `<h1 id="a-b">A b</h1><h2 id="a-b-1">A b</h2><h1 id="setext">Setext</h1><h3 id="c">C?</h3>` |
| `test_fenced_code_not_parsed` | ```` ```py\nx = *a* <b>\n```\n~~~\n# no\n~~~ ```` | `<pre><code class="language-py">x = *a* &lt;b&gt;</code></pre><pre><code># no</code></pre>` |
| `test_unterminated_fence_runs_to_end` | ```` text\n```\ncode\n# not heading ```` | `<p>text</p><pre><code>code\n# not heading</code></pre>` |
| `test_indented_code` | `para\n\n    a < b\n` | `<p>para</p><pre><code>a &lt; b</code></pre>` |
| `test_inline` | ``a `*x*` **b** _c_ [l](u "t") <https://e.x> ![alt](i.png) snake_case_name`` + two trailing spaces + `\nnext` | `<p>a <code>*x*</code> <strong>b</strong> <em>c</em> <a href="u" title="t">l</a> <a href="https://e.x">https://e.x</a> alt snake_case_name<br>next</p>` |
| `test_lists_nested` | `- a\n- b\n  1. c\n  2. d\n- e` | `<ul><li>a</li><li>b<ol><li>c</li><li>d</li></ol></li><li>e</li></ul>` |
| `test_blockquote_hr` | `> q *x*\n\n---` | `<blockquote><p>q <em>x</em></p></blockquote><hr>` |
| `test_table` | `\| a \| b \|\n\|---\|:-:\|\n\| 1 \| x\\\|y \|` | `<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>1</td><td>x\|y</td></tr></tbody></table>` |
| `test_raw_html_passes_script_dropped` | `<details><summary>S</summary>\n\nbody\n</details>\n<script>x()</script>` | contains `<details><summary>S</summary>` and `<p>body</p>`, not `x()` |
| `test_front_matter` | `---\ntitle: "T"\ndescription: D d\n---\n# H` | `front_matter` -> `({"title": "T", "description": "D d"}, "# H")`; `md_to_html` -> `<h1 id="h">H</h1>` |
| `test_mdx_imports_comments_dropped` | `import X from './x'\nexport const y = 1\n{/* note */}\ntext` | `<p>text</p>` |
| `test_mdx_components` | `<CardGroup cols={2}>\n<Card title="Go" href="/go">\nGo docs\n</Card>\n<Note title='Hi'>\nkeep me\n</Note>\n</CardGroup>` | `<p><a href="/go">Go</a></p><p>Go docs</p><p><strong>Hi</strong></p><p>keep me</p>` |
| `test_mdx_multiline_tag_and_dedent` | `<Tabs>\n  <Tab\n    title="npm"\n  >\n    ```bash\n    npm i x\n    ```\n  </Tab>\n</Tabs>` | `<p><strong>npm</strong></p><pre><code class="language-bash">npm i x</code></pre>` |
| `test_mdx_inline_component` | `<Note>Read [run](/r).</Note>` | `<p>Read <a href="/r">run</a>.</p>` |
| `test_mdx_unclosed_component_keeps_text` | `<Note>\nstill here\n\n## After` | `<p>still here</p><h2 id="after">After</h2>` |
| `test_jsx_in_code_kept` | ```` ```jsx\n<Card title="x" />\n``` ```` | `<pre><code class="language-jsx">&lt;Card title="x" /&gt;</code></pre>` |

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k MarkdownTests -v`
Expected: ERROR, no module `build_markdown`.

- [ ] **Step 3: Implement `build_markdown.py`**

Approach (spec: line-based block parser):
1. `front_matter`, then an MDX pre-pass over lines that tracks fences (never touches lines inside a fence): drop top-level `import `/`export ` lines and lines that are only `{/* ... */}`; find capitalized tags `<Name ...>`, `</Name>`, `<Name ... />` (an opening tag may span lines until a `>` outside `"..."`, `'...'`, `{...}`); a tag alone on its line(s) is replaced: one carrying `href` and `title` by a line `[title](href)`, one with only `title` by a line `**title**`, others by a blank line; a tag sharing a line with text is removed in place (text kept); dedent each component's body by the minimum indent of its non-blank lines (unclosed component: body runs to end of page).
2. Block parse: fences (``` and ~~~, info string's first word -> `language-<lang>`), indented code (4 spaces after a blank line or at start), ATX/setext headings, `---`/`***`/`___` rules, blockquotes (recursive), lists (marker `-*+` or `N.`/`N)`; nesting by indent; tight lists render items without `<p>`), pipe tables (header + delimiter row), raw HTML lines starting with a lowercase tag, paragraphs.
3. Inline: protect code spans first; then autolinks, images (-> escaped alt), links (optional `"title"`), `**`/`__` strong, `*`/`_` em (`_` only at word boundaries), trailing two spaces or `\` -> `<br>`; lowercase inline HTML tags pass through; other text HTML-escaped.
4. Join blocks with `"\n"`, return `build_html._serialize(build_html._tokens(html))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: same command. Expected: all pass; whole file passes.

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build/scripts/build_markdown.py tests/test_docshelf_build.py
git commit -m "docshelf-build: stdlib Markdown/MDX to HTML converter"
```

---

### Task 3: Page signals

**Files:**
- Modify: `skills/docshelf-build/scripts/build_markdown.py`
- Test: `tests/test_docshelf_build.py` (class `SignalsTests`)

**Interfaces:**
- Produces: `page_signals(text: str, kind: str) -> dict` with keys `words: int`, `code_ratio: float` (3 decimals), `you_per_1k: float` (1 decimal), `steps: int`, `signature_lines: int`, `headings: int`, `tables: int`. `kind` is `"md"` or `"html"`.

- [ ] **Step 1: Write the failing tests**

```python
SIGNALS_MD = """---
title: T
---
# Install

You can install it. Let's go, your way.

## Step 1: get it

1. Download
2. Run

```bash
tool --flag
def f(x):
```

| a | b |
|---|---|
| 1 | 2 |
"""

class SignalsTests(unittest.TestCase):
    def test_markdown_signals(self):
        self.assertEqual(page_signals(SIGNALS_MD, "md"), {
            "words": 16, "code_ratio": 0.167, "you_per_1k": 187.5, "steps": 3,
            "signature_lines": 1, "headings": 1, "tables": 1})

    def test_html_signals(self):
        html = ("<main><h2>Step one</h2><p>You run it.</p><pre>--verbose\nx = 1</pre>"
                "<ol><li>a</li></ol><table><tr><td>z</td></tr></table></main>")
        s = page_signals(html, "html")
        self.assertEqual((s["headings"], s["tables"], s["steps"], s["signature_lines"]), (1, 1, 2, 1))
        self.assertGreater(s["code_ratio"], 0)

    def test_empty_page(self):
        self.assertEqual(page_signals("", "md")["you_per_1k"], 0.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k SignalsTests -v`
Expected: ImportError / AttributeError for `page_signals`.

- [ ] **Step 3: Implement `page_signals`**

Definitions the test pins (Markdown; front matter excluded):
- non-blank lines include fence lines; code lines = lines inside fenced or indented code (not the fences); `code_ratio = round(code / nonblank, 3)` (0.0 when no lines).
- `words` = `len(re.findall(r"[A-Za-z][A-Za-z']*", line))` summed over non-code, non-fence lines, with table delimiter rows skipped.
- `you_per_1k` counts whole words, case-insensitive: `you`, `your`, `let's`, `we'll`; `round(n * 1000 / words, 1)`, 0.0 when `words == 0`.
- `steps` = ordered-list items + headings (any level) whose text starts with `Step`.
- `signature_lines` = code or heading lines matching any of `\b[A-Za-z_][\w.]*\(.*\)`, `^\s*(def|class|function|interface)\s`, `^\s*type\s+\w+\s*=`, `^\s*--?[A-Za-z]`.
- `headings` = `##`/`###` (and setext `---` level 2); `tables` = pipe tables.
For `"html"`: same rules over `main_content(text)` tokens: `<pre>` text lines are code lines, `h2`/`h3` headings, `<table>` tables, `<ol><li>` steps, text of other block elements is one line per block.

- [ ] **Step 4: Run tests** - same command, expect PASS; whole file PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build/scripts/build_markdown.py tests/test_docshelf_build.py
git commit -m "docshelf-build: per-page signals for the later classifier"
```

---

### Task 4: Fetching llms pages and the page cache (`build_fetch.py`, `build_core.py`)

**Files:**
- Modify: `skills/docshelf-build/scripts/build_fetch.py`, `skills/docshelf-build/scripts/build_core.py`
- Test: `tests/test_docshelf_build.py` (class `LlmsFetchTests`)

**Interfaces:**
- Consumes: `fake_opener` test helper (existing).
- Produces:
  - `build_core.src_dir(cache: str) -> str` = `<cache>/built-src`.
  - `Source._allowed(url)` becomes per host (robots cached per `scheme://netloc`); 0.1.0 behavior for Sphinx unchanged.
  - `Source.get_url(url: str) -> bytes`: robots check + `_get`; raises `FetchError(url, reason)`.
  - `open_url_source(workers=1, delay=0.5, opener=None, sleep=None) -> Source` (a `Source` with `base=""`, `is_url=True`, `live_base=None`).
  - `index_getter(source: Source) -> Callable[[str], str]`: `get_url` decoded UTF-8 (replace); a `FetchError` becomes `CLIError("cannot fetch <url>: <reason>", 4)`.
  - `looks_html(body: str) -> bool`: after whitespace, starts with `<!doctype` or `<html` (case-insensitive).
  - `fetch_llms_page(source: Source, url: str) -> Tuple[str, str]`: `(text, type)` with `type in ("md", "html")`; `.md` retry rule from the spec (retry URL = `url.rstrip("/") + ".md"`, only when `url`'s path does not end `.md`/`.mdx`).
  - `class PageCache(root: str)`: `get(key) -> Optional[Tuple[str, str]]`, `put(key, url, text, type, now: float) -> None` (atomic per file, manifest updated atomically; `ValueError` when the key resolves outside `root`), `manifest() -> dict`.
  - `fetch_llms(source: Source, pages: List[Tuple[str, str]], cache: PageCache, refetch: bool, now: float) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, str], Dict[str, str]]`: `(raw by key, error by key, fetched ISO time by key)`; `pages` are `(key, url)`; cached pages used unless `refetch`; a failed page falls back to its cached copy if any (still reported in errors); delay/sleep and workers as `fetch_pages`.

- [ ] **Step 1: Write the failing tests**

```python
class LlmsFetchTests(unittest.TestCase):
    # setUp: temp dir, self.cache = PageCache(os.path.join(tmp, "built-src", "demo"))
    def test_md_retry_when_html(self):
        op = fake_opener([(200, b"<!DOCTYPE html><html>x</html>"), (200, b"# Real")])
        src = open_url_source(opener=op, sleep=lambda s: None)
        self.assertEqual(fetch_llms_page(src, "https://x.io/docs/a"), ("# Real", "md"))
        self.assertEqual(op.urls[-1], "https://x.io/docs/a.md")

    def test_md_retry_fails_keeps_html(self):
        op = fake_opener([(200, b"  <html><main><p>x</p></main></html>"), (404, b"")])
        text, kind = fetch_llms_page(open_url_source(opener=op, sleep=lambda s: None), "https://x.io/docs/a/")
        self.assertEqual(kind, "html")
        self.assertEqual(op.urls[-1], "https://x.io/docs/a.md")

    def test_no_retry_for_md_url(self):
        op = fake_opener([(200, b"<html>odd</html>")])
        self.assertEqual(fetch_llms_page(open_url_source(opener=op, sleep=lambda s: None),
                                         "https://x.io/a.md")[1], "html")
        self.assertEqual(len([u for u in op.urls if not u.endswith("robots.txt")]), 1)

    def test_robots_per_host(self):
        # robots on x.io disallows /private; other.io (404 robots) allowed:
        # get_url("https://x.io/private/a.md") raises FetchError "blocked by robots.txt";
        # get_url("https://other.io/private/a.md") succeeds; robots.txt fetched once per host.

    def test_cache_put_get_manifest(self):
        self.cache.put("docs/a", "https://x.io/docs/a.md", "# A", "md", now=0)
        self.assertEqual(self.cache.get("docs/a"), ("# A", "md"))
        m = self.cache.manifest()["docs/a"]
        self.assertEqual((m["url"], m["type"], m["fetched"]), ("https://x.io/docs/a.md", "md", "1970-01-01T00:00:00Z"))
        self.assertEqual(m["sha256"], hashlib.sha256(b"# A").hexdigest())
        self.assertTrue(os.path.isfile(os.path.join(self.cache.root, "docs", "a.md")))

    def test_cache_refuses_escape(self):
        with self.assertRaises(ValueError):
            self.cache.put("../evil", "https://x.io/e.md", "x", "md", now=0)

    def test_fetch_llms_uses_cache_and_refetch(self):
        self.cache.put("a", "https://x.io/a.md", "# old", "md", now=0)
        op = fake_opener([(200, b"# B")])
        raw, errors, fetched = fetch_llms(open_url_source(opener=op, sleep=lambda s: None),
                                          [("a", "https://x.io/a.md"), ("b", "https://x.io/b.md")],
                                          self.cache, refetch=False, now=60)
        self.assertEqual(raw, {"a": ("# old", "md"), "b": ("# B", "md")})
        self.assertEqual([u for u in op.urls if not u.endswith("robots.txt")], ["https://x.io/b.md"])
        self.assertEqual((errors, list(fetched)), ({}, ["b"]))
        op2 = fake_opener([(200, b"# new")])
        raw, _, _ = fetch_llms(open_url_source(opener=op2, sleep=lambda s: None),
                               [("a", "https://x.io/a.md")], self.cache, refetch=True, now=120)
        self.assertEqual(raw["a"], ("# new", "md"))

    def test_fetch_llms_failure_keeps_cached_copy(self):
        self.cache.put("a", "https://x.io/a.md", "# old", "md", now=0)
        op = fake_opener([(404, b"")])
        raw, errors, _ = fetch_llms(open_url_source(opener=op, sleep=lambda s: None),
                                    [("a", "https://x.io/a.md")], self.cache, refetch=True, now=1)
        self.assertEqual((raw["a"], errors["a"]), (("# old", "md"), "HTTP 404"))
```

(Write `test_robots_per_host` fully.) Also keep every existing `FetchTests` test green: run the whole file.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k LlmsFetchTests -v`
Expected: ImportError for `open_url_source` etc.

- [ ] **Step 3: Implement** the interfaces above. `PageCache` file path = `root/<key>.<type>`; check `os.path.commonpath([realpath(path), realpath(root)]) == realpath(root)`; write via `tempfile.mkstemp` + `os.replace` (pattern from `build_plan.save_plan`); `fetched` ISO format `%Y-%m-%dT%H:%M:%SZ` UTC. A `put` with a different `type` than a cached file removes the old file.

- [ ] **Step 4: Run tests** - same command, PASS; whole file PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build/scripts/build_fetch.py skills/docshelf-build/scripts/build_core.py tests/test_docshelf_build.py
git commit -m "docshelf-build: per-host robots, .md retry and page cache"
```

---

### Task 5: Plans: `model:` rule, llms plan, llms summary (`build_plan.py`)

**Files:**
- Modify: `skills/docshelf-build/scripts/build_plan.py`
- Test: `tests/test_docshelf_build.py` (extend `PlanTests`; new `LlmsPlanTests`)

**Interfaces:**
- Consumes: `build_llms.Tree`, `build_llms.LlmsPage` (Task 1).
- Produces:
  - `make_plan(...)` (Sphinx) unchanged signature; output gains `"kind": "sphinx"`; applies the precedence below.
  - `make_llms_plan(source: str, tree: Tree, overrides: List[Tuple[str, str]], old: Optional[dict] = None, reset: bool = False) -> dict`.
  - `summarize_llms(plan: dict, old: Optional[dict]) -> List[str]`.
  - `CARRIED = ("signals", "fetched", "fetch_error")`.
- Precedence per page, both kinds (lowest to highest): rule -> stored overrides (dropped by `reset`) -> old `why` starting `model:` keeps old `keep`, `description`, `why` (dropped by `reset`) -> overrides given on this command line -> old `why == "manual"` (as 0.1.0, unaffected by `reset`). Old `CARRIED` fields are copied for pages still listed (llms plans).
- llms plan fields: `format`, `kind: "llms"`, `source`, `base_url: None`, `index_sha256`, `indexes`, `project` (tree title), `version: ""`, `entry_count` (page count), `rule: "llms-all"`, `overrides`, `pages` keyed by page key with `keep`, `title`, `section`, `description` (index note, else old description), `why`, `uri` (absolute URL).

- [ ] **Step 1: Write the failing tests**

```python
SRC_LLMS = "https://x.io/llms.txt"

def llms_tree(pages, indexes=None, sha="s1", title="OpenCode"):
    """Tree(title, "x.io", [LlmsPage(key, "https://x.io/%s.md" % key, key.upper(), section, None)],
    indexes or [{"url": SRC_LLMS, "title": title, "pages": len(pages), "parent": None, "note": None}], sha)"""

class LlmsPlanTests(unittest.TestCase):
    def test_all_full(self):
        plan = make_llms_plan("https://x.io/llms.txt", llms_tree([("docs/a", "Docs"), ("pricing", "Optional")]), [])
        self.assertEqual((plan["kind"], plan["rule"], plan["project"], plan["version"]), ("llms", "llms-all", "OpenCode", ""))
        self.assertEqual({k: (p["keep"], p["why"]) for k, p in plan["pages"].items()},
                         {"docs/a": ("full", "llms: all"), "pricing": ("full", "llms: all")})
        self.assertEqual(plan["pages"]["docs/a"]["uri"], "https://x.io/docs/a.md")

    def test_model_choice_survives_replan_but_not_cli_override_or_reset(self):
        old = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs"), ("docs/b", "Docs")]), [])
        old["pages"]["docs/a"].update(keep="stub", why="model:emb-1", description="guide", signals={"words": 9})
        again = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs"), ("docs/b", "Docs")], sha="s2"), [], old=old)
        self.assertEqual((again["pages"]["docs/a"]["keep"], again["pages"]["docs/a"]["why"],
                          again["pages"]["docs/a"]["signals"]), ("stub", "model:emb-1", {"words": 9}))
        cli = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs")]), [("full", "docs/*")], old=old)
        self.assertEqual(cli["pages"]["docs/a"]["why"], "override: docs/*")
        reset = make_llms_plan(SRC_LLMS, llms_tree([("docs/a", "Docs")]), [], old=old, reset=True)
        self.assertEqual(reset["pages"]["docs/a"]["why"], "llms: all")

    def test_summary(self):
        tree = llms_tree([("a", "Docs"), ("b", "Docs"), ("c", "Optional")],
                         indexes=[{"url": "https://x.io/llms.txt", "title": "R", "pages": 1, "parent": None, "note": None},
                                  {"url": "https://x.io/_llms/python.txt", "title": "P", "pages": 2,
                                   "parent": "https://x.io/llms.txt", "note": None},
                                  {"url": "https://other.io/llms.txt", "title": "E", "pages": None,
                                   "parent": "https://x.io/llms.txt", "note": "other host, not followed"}])
        lines = summarize_llms(make_llms_plan(SRC_LLMS, tree, []), None)
        self.assertEqual(lines[:5], ["OpenCode: 3 pages: 3 full, 0 stub",
                                     "  Docs: 2   Optional: 1",
                                     "index tree:",
                                     "  llms.txt (1)",
                                     "    _llms/python.txt (2)"])
        self.assertIn("    https://other.io/llms.txt (other host, not followed)", lines)

    def test_summary_warns_over_300(self):
        tree = llms_tree([("p%d" % i, "Docs") for i in range(301)])
        self.assertTrue(any(l.startswith("warning: 301 full pages") for l in
                            summarize_llms(make_llms_plan(SRC_LLMS, tree, []), None)))
```

Also in `PlanTests`: `test_kind_sphinx` (`make_plan(...)["kind"] == "sphinx"`) and `test_sphinx_model_choice_kept` (same three assertions as above on a Sphinx plan with an old page `why="model:x"`).

Summary format decisions pinned by the test: first line `"<project>: N pages: F full, S stub"`; second line top-level section parts (`section.split(" / ")[0]`, `"Pages"` when None) sorted by count desc then name, `"%s: %d"` joined by three spaces, at most 8; then `index tree:`, each index indented 2 spaces per depth plus 2, shown as URL path without leading `/` when on the main host, else the full URL; skipped indexes show `(note)` instead of a count; added/dropped lines as 0.1.0; over 300 full: `warning: N full pages; narrow with a sub-index as SOURCE (see the tree) or --stub globs`.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k PlanTests -v` (matches both classes)
Expected: ImportError for `make_llms_plan`.

- [ ] **Step 3: Implement** the interfaces; factor the precedence into one helper `_choose(key, rule_keep, rule_why, stored, cli, prev) -> Tuple[str, str]` used by both `make_plan` and `make_llms_plan`. `make_plan` must now keep stored and command-line overrides apart: in `make_plan`, `stored` = old overrides (unless reset), `cli` = the `overrides` argument.

- [ ] **Step 4: Run tests** - same command PASS; whole file PASS (existing `PlanTests` unchanged in behavior).

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build/scripts/build_plan.py tests/test_docshelf_build.py
git commit -m "docshelf-build: llms plans, model: choices survive re-planning"
```

---

### Task 6: llms docvol: link rewriting, heading entries, `source_kind`

**Files:**
- Modify: `skills/docshelf-build/scripts/build_html.py`, `skills/docshelf-build/scripts/build_docvol.py`
- Test: `tests/test_docshelf_build.py` (class `LlmsDocvolTests`; existing `DocvolTests` stay green)

**Interfaces:**
- Consumes: `md_to_html` (Task 2), `main_content` (existing), plan from `make_llms_plan` (Task 5).
- Produces:
  - `build_html.headings(content: str) -> List[Tuple[int, str, str]]`: `(level, id, text)` for `h2`/`h3` with an `id`, document order.
  - `build_html.rewrite_url_links(content: str, page_key: str, page_url: str, keys_by_url: Dict[str, str], main_host: str) -> str`: resolve each `href` against `page_url`; when the URL (without fragment; also tried with `.md`/`.mdx` stripped, with `.md` added, and with a trailing `/` <-> `/index`) is in `keys_by_url` -> `posixpath.relpath(key, dirname(page_key) or ".") + "#" + anchor`; same-page `#x` -> `#` + `anchor_id`; anything else -> the absolute resolved URL (so relative links to unstored same-site pages become live URLs; external links unchanged).
  - `build_docvol.write_llms_docvol(cache: str, name: str, plan: dict, raw: Dict[str, Tuple[str, str]], errors: Dict[str, str], now: float) -> dict` (meta, with `"reused"` = keys that fell back to the previous docvol copy). `meta.json` gets `"source_kind": "llms"`, `"index_sha256"` in place of `"inventory_sha256"`.
  - The atomic file writing of `write_docvol` moves into `_write_files(cache: str, name: str, data: Dict[str, object]) -> None`, used by both.

Index entries (spec "Index entries"): per page `{"name": title, "type": T, "path": key}` with `T` = top-level part of `section` or `"Pages"`; per full page also one entry per `headings()` item `{"name": text, "type": T, "path": key + "#" + id}`. Stubs: page entry only. Full page content: `md` -> `md_to_html`, `html` -> `main_content`; then `rewrite_url_links`. A full page missing from `raw` keeps the previous docvol copy if it is not a stub (as 0.1.0), else `stub_html(..., url=p["uri"], note=errors.get(key, "not fetched"))`. Stub pages: `stub_html(title, section, description, p["uri"], None)`.

- [ ] **Step 1: Write the failing tests**

```python
class LlmsDocvolTests(unittest.TestCase):
    # setUp: temp cache; plan = make_llms_plan(SRC_LLMS, llms_tree([("docs/a","Docs"),("docs/b","Docs"),("pricing",None)]), [])
    #        plan["pages"]["pricing"]["keep"] = "stub"
    def test_links_rewritten(self):
        keys = {"https://x.io/docs/a.md": "docs/a", "https://x.io/docs/b.md": "docs/b"}
        html = ('<a href="b.md#x y">b</a><a href="/docs/b">b2</a><a href="/blog/">blog</a>'
                '<a href="https://e.x/">e</a><a href="#Top">t</a>')
        self.assertEqual(rewrite_url_links(html, "docs/a", "https://x.io/docs/a.md", keys, "x.io"),
                         '<a href="b#x_y">b</a><a href="b">b2</a><a href="https://x.io/blog/">blog</a>'
                         '<a href="https://e.x/">e</a><a href="#Top">t</a>')

    def test_headings(self):
        self.assertEqual(headings('<h1 id="t">T</h1><h2 id="a">A <code>x</code></h2><h3>no id</h3><h3 id="b">B</h3>'),
                         [(2, "a", "A x"), (3, "b", "B")])

    def test_write_llms_docvol(self):
        raw = {"docs/a": ("# A\n\n## Usage\n\nSee [b](b.md).\n", "md"),
               "docs/b": ("<html><nav>n</nav><main><h2 id='k'>K</h2></main></html>", "html")}
        meta = write_llms_docvol(self.cache, "demo", self.plan, raw, {}, now=0)
        folder = os.path.join(self.cache, "built", "demo")
        index, db, meta_disk = (load(folder, f) for f in ("index.json", "db.json", "meta.json"))
        self.assertEqual(meta_disk["source_kind"], "llms")
        self.assertEqual(meta_disk["format"], 1)
        self.assertIn({"name": "Usage", "type": "Docs", "path": "docs/a#usage"}, index["entries"])
        self.assertIn({"name": "K", "type": "Docs", "path": "docs/b#k"}, index["entries"])
        self.assertIn({"name": "PRICING", "type": "Pages", "path": "pricing"}, index["entries"])
        self.assertIn('href="b"', db["docs/a"])
        self.assertNotIn("<nav>", db["docs/b"])
        self.assertIn("https://x.io/pricing.md", db["pricing"])

    def test_failed_page_keeps_previous_copy(self):
        # build once with docs/a content, then again with raw lacking docs/a and errors {"docs/a": "HTTP 500"}:
        # db["docs/a"] unchanged and meta["reused"] == ["docs/a"].
        # Then remove the docvol folder and write again with the same raw/errors:
        # db["docs/a"] is a stub containing "HTTP 500" and "https://x.io/docs/a.md".
```

(Write the last test fully.) If `docshelf_reads_built()` is true, add `test_docshelf_reads_llms_docvol`: write the docvol, then run `docshelf.py search Usage` with the test env (pattern from `CliTests.run_docshelf`) and assert exit 0 and `docs/a#usage` in stdout.

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k Docvol -v`
Expected: ImportError for `rewrite_url_links` / `write_llms_docvol`.

- [ ] **Step 3: Implement** the interfaces; `write_docvol` keeps its behavior (existing `DocvolTests` unchanged) but calls `_write_files`.

- [ ] **Step 4: Run tests** - same command PASS; whole file PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build/scripts/build_html.py skills/docshelf-build/scripts/build_docvol.py tests/test_docshelf_build.py
git commit -m "docshelf-build: write llms docvols with heading entries"
```

---

### Task 7: Command line, version, SKILL.md

**Files:**
- Modify: `skills/docshelf-build/scripts/docshelf_build.py`, `skills/docshelf-build/scripts/build_core.py` (`VERSION = "0.2.0"`), `skills/docshelf-build/SKILL.md`
- Test: `tests/test_docshelf_build.py` (class `LlmsCliTests`)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `main(argv=None, env=None, opener=None, sleep=None) -> int` (`opener`/`sleep` passed to every `open_source`/`open_url_source`; tests use them, users never do).
  - `plan` with an llms SOURCE (`is_llms_source`): `read_tree` -> name (`--name` or `derive_name({"project": tree.title})`) -> `check_name` -> `make_llms_plan` -> `save_plan` -> `summarize_llms`; `--base-url` with an llms SOURCE -> `CLIError("--base-url is only for Sphinx sources", 2)`.
  - `build` with an llms plan (`plan.get("kind") == "llms"`): re-read the tree; when `index_sha256` changed, re-plan (`make_llms_plan(..., [], old=plan)`), save, print `the index changed since the plan:` and the summary. Then `fetch_llms` for full pages (`PageCache(os.path.join(src_dir(cache), name))`, `--refetch`); for each fetched raw page set `signals` (`page_signals`), `fetched` (from `fetch_llms`), drop `fetch_error`; for errors set `fetch_error`; when a page's `description` is None, fill from `front_matter` description; when its title is empty, from front matter title. Save the plan, then `write_llms_docvol`. All full pages failing with no cached copy -> `CLIError` code 4 as 0.1.0. Output line: `built NAME: F full, S stub, X failed; E entries (folder)`.
  - `--refetch` on `build` (help: "download pages again instead of using the page cache (llms.txt sources; Sphinx builds have no page cache)").
  - `remove NAME` also deletes `<cache>/built-src/NAME`; `"page cache"` joins the `did` list.
  - `DESCRIPTION` mentions both source kinds.

- [ ] **Step 1: Write the failing tests**

```python
OC_INDEX = "# OpenCode\n## Docs\n- [Build](https://x.io/docs/build.md): build agents\n- [Run](https://x.io/docs/run)\n## Optional\n- [Pricing](https://x.io/pricing.md)\n"
BUILD_MD = "---\ntitle: Build\n---\nimport X from 'x'\n# Build\n\n<Note>Read [run](/docs/run).</Note>\n\n## Options\n\n```bash\nopencode run\n--model NAME\n```\n"
# signature_lines == 1 (the "--model" line)

class LlmsCliTests(unittest.TestCase):
    # setUp like CliTests (env with DOCSHELF_CACHE_DIR); self.site: dict url -> (status, body);
    # opener(url): robots -> 404; else self.site.get(url, (404, b"")); records urls.
    def test_plan_then_build_then_warm_rebuild(self):
        code, out, _ = self.run_main("plan", "https://x.io/llms.txt")
        self.assertEqual(code, 0)
        self.assertIn("opencode: 3 pages: 3 full, 0 stub", out)
        self.assertIn("  llms.txt (3)", out)
        code, out, _ = self.run_main("build", "opencode")
        self.assertEqual(code, 0, out)
        plan = load_plan(self.plan_path)
        self.assertEqual(plan["pages"]["docs/build"]["signals"]["signature_lines"], 1)
        self.assertIn("fetched", plan["pages"]["docs/run"])
        self.urls.clear()
        self.assertEqual(self.run_main("build", "opencode")[0], 0)
        self.assertEqual([u for u in self.urls if not u.endswith("robots.txt")], ["https://x.io/llms.txt"])

    def test_md_retry_through_cli(self):  # docs/run serves HTML, docs/run.md serves Markdown -> cache file docs/run.md

    def test_index_change_replans(self):  # change OC_INDEX (add a page) -> build prints "the index changed" and "added 1 page: docs/new"

    def test_subindex_source_same_keys(self):
        # root links /_llms/py.txt; plan root, then plan /_llms/py.txt --name py: same keys for shared pages

    def test_failed_page_records_error_keeps_copy(self):
        # build, then make docs/run 500 and build --refetch: exit 0, plan has fetch_error "HTTP 500",
        # db.json still holds the old docs/run content

    def test_base_url_rejected(self):
        code, _, err = self.run_main("plan", "https://x.io/llms.txt", "--base-url", "https://x.io/")
        self.assertEqual(code, 2)
        self.assertIn("--base-url", err)

    def test_not_an_index(self):  # llms.txt returns HTML 200 -> code 3, no plan file

    def test_remove_deletes_page_cache(self):  # after build: remove opencode -> built-src/opencode gone, plan kept

    def test_version(self):  # "--version" output contains build_core.VERSION; SKILL.md metadata.version == build_core.VERSION
```

(Write every stub test fully with the fixtures above.) Existing `CliTests` must stay green (they call `main(argv, env=...)`).

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests -p test_docshelf_build.py -k LlmsCliTests -v`
Expected: failures (`main()` has no `opener`; plan with a `.txt` SOURCE goes the Sphinx way).

- [ ] **Step 3: Implement** the CLI changes; set `VERSION = "0.2.0"` and SKILL.md `version: "0.2.0"`. SKILL.md: description becomes `Use when documentation you need offline is not on DevDocs or in Dash/Zeal but its site publishes a Sphinx objects.inv (Sphinx, PyDoctor, MkDocs with mkdocstrings) or an llms.txt page list (Mintlify, Starlight and others), to build a trimmed docshelf docvol from it.`; add a short "llms.txt sites" section: SOURCE forms, every page kept in full, read the index tree and narrow with a sub-index or `--stub` before building large sites, page cache and `--refetch`, `signals` are for a later classifier (`why: "model:<id>"` survives re-planning).

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s tests -v 2>&1 | tail -5`
Expected: `OK` (skips allowed only where they existed before).

- [ ] **Step 5: Commit**

```bash
git add skills/docshelf-build tests/test_docshelf_build.py
git commit -m "docshelf-build 0.2.0: llms.txt sources on the command line"
```

---

### Task 8: Live trial, notes, PR

**Files:**
- Modify: `AGENTS.md` (`docshelf-build` skill entry), `TODO.md`

- [ ] **Step 1: Live trial (network, not a test).** With `DOCSHELF_CACHE_DIR` set to a scratch folder: `plan https://opencode.ai/llms.txt`, `build opencode`, rebuild (expect index request only); then `plan` a LangChain sub-index (pick one from `https://docs.langchain.com/llms.txt`'s tree, under 300 pages) and `build` it. Record: page counts, failures and reasons, `.md` retries, signals spread (min/median/max of `words`, `code_ratio`, `you_per_1k`, `signature_lines` via a short `python3 -c` over the plan), and docshelf `search` on one known API name. Fix any bug found with a test first (TDD), as a further commit.
- [ ] **Step 2: Notes.** AGENTS.md entry: add llms.txt sources (index tree, every page full, page cache `<cache>/built-src/`, signals and `model:` choices for the later classifier). TODO.md: mark 8.9 done; add a new item for the classifier step (cheap thresholds / embedding classifier trained on Sphinx role labels / decision model, writing `keep` and `why: model:<id>`), with the trial's signal spread as its starting data.
- [ ] **Step 3: Checks.** `python3 -m unittest discover -s tests -v` OK; `python3 scripts/ci_changed_skills.py --check-versions` (see its `--help` for the base argument) passes; `python3 scripts/build_skills_index.py --check` (stale is fine: CI regenerates on `main`); read the whole diff for public-repo safety.
- [ ] **Step 4: Commit and push** `update/docshelf-build`; open the PR with `.github/pull_request_template.md`'s headings filled (Kind, What changed, Skill and version 0.2.0, checklist, Testing incl. the live trial numbers, Docs touched, Follow-ups: classifier). Merge with a merge commit only after the user approves.
