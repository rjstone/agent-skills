# docshelf-build Doxygen sites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `doxygen` site type in docshelf-build that turns a Doxygen HTML
site (GLFW, wxWidgets, Arm CMSIS, ...) into a docshelf docvol, read from the
search index or, without one, from `menudata.js` and the typed index pages.

**Architecture:** A new `scripts/build_doxygen.py` reads either index and
returns `InvEntry` objects with `doxygen:<Type>` / `std:doc` roles, so the
existing Sphinx plan, fetch and docvol path does the rest. `make_plan` gains
a `kind` with the Doxygen page rule; `main_content` learns Doxygen's
`div.header` + `div.contents`; `detect` and the CLI dispatch on the new kind.

**Tech Stack:** Python 3 stdlib only (`html.parser`, `re`, `hashlib`,
`urllib`); `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-23-docshelf-build-doxygen-design.md`
(approved 2026-11-23). Read it with this plan.

## Global Constraints

- Stdlib only; no `eval`, no general JS parser.
- Branch `update/docshelf-build`; draft PR #38 stays a draft until the GLFW
  and wxWidgets trials pass (Task 9). Merge commit, never squash.
- `metadata.version` "0.4.1" -> "0.5.0" in `skills/docshelf-build/SKILL.md`
  and `VERSION = "0.5.0"` in `scripts/build_core.py` (Task 8).
- Docvol `"format": 1` unchanged; `build_docvol.py` unchanged
  (`role_label("doxygen:Function")` already returns "Function").
- Tests go in `tests/test_docshelf_build.py` (a separate file would be
  mapped by CI to a skill that does not exist), in new classes named
  `Doxygen*Tests`, with hand-made fixtures only: never copy a real site's
  generated files into the repo.
- Public repo: no machine/account details; real site URLs only in
  `BUILD-doxygen.md`, the spec and trial notes.
- Politeness unchanged: every request through `Source` (robots.txt per
  host and redirect hop, retries, one request at a time).
- Type names: Class, Struct, Namespace, Function, Variable, Type, Enum,
  Constant, Macro, Property, Module, File; prose pages `std:doc`.
- Test command (repo root):
  `python3 -m unittest discover -s tests -p test_docshelf_build.py -k Doxygen -v`;
  full suite: `python3 -m unittest discover -s tests`.

## Review Focus

1. A bot-protection HTML page answered with status 200 for a `.js` index
   file: must fail with a clear "may be blocking automated requests" error,
   not parse as an empty index (Task 1 and Task 3 tests).
2. Some index files missing or garbled (404, truncated JS): warn per file
   and keep the rest; only "every file failed" is fatal (Task 3, Task 4).
3. Search-index URLs are relative to `search/` (`../x.html#a`) and member
   index URLs to the site root; both must become the same page uri
   (`x.html`) or pages split in two (Task 3, Task 4).
4. The same member listed in two categories or as several overloads:
   one entry per (name, page, anchor), overloads kept (Task 3).
5. A page URL deep in the site (`.../group__window.html`) or a base
   without a trailing slash given to `detect`/`plan` (Task 7).

---

### Task 1: JS literal reader

**Files:**
- Create: `skills/docshelf-build/scripts/build_doxygen.py`
- Test: `tests/test_docshelf_build.py` (class `DoxygenJsTests`)

**Interfaces:**
- Produces: `class DoxygenFormatError(ValueError)`;
  `js_value(text: str, var: str) -> object`: finds `var <var>` `=` and
  parses the literal after it: arrays -> `list`, objects -> `dict` (keys
  quoted or bare identifiers), single- or double-quoted strings (backslash
  escapes `\\ \' \" \n \t \uXXXX`), integers, `true`/`false`. Comments
  (`/* */`, `//`) skipped. Raises `DoxygenFormatError` on anything else,
  and with the message containing "may be blocking automated requests"
  when `text.lstrip()` starts with `<`.

- [ ] **Step 1: Write the failing tests**

```python
class DoxygenJsTests(unittest.TestCase):
    def test_search_data(self):
        text = "var searchData=\n[\n  ['_5fget_0',['_get',['../a.html#x',1,'ns::A::_get()']]]\n];\n"
        self.assertEqual(js_value(text, "searchData"),
                         [["_5fget_0", ["_get", ["../a.html#x", 1, "ns::A::_get()"]]]])

    def test_menudata_bare_keys_and_comment(self):
        text = '/* @licstart x */ var menudata={children:[{text:"Main Page",url:"index.html"}]}'
        self.assertEqual(js_value(text, "menudata"),
                         {"children": [{"text": "Main Page", "url": "index.html"}]})

    def test_escapes(self):
        self.assertEqual(js_value(r"var v=['it\'s','a\\b','é'];", "v"), ["it's", "a\\b", "é"])

    def test_object_with_int_keys(self):
        self.assertEqual(js_value('var s =\n{\n  0: "all",\n  1: "classes"\n};', "s"),
                         {"0": "all", "1": "classes"})

    def test_html_instead_of_js(self):
        with self.assertRaisesRegex(DoxygenFormatError, "blocking automated requests"):
            js_value("<!DOCTYPE html><title>Just a moment...</title>", "searchData")

    def test_missing_var_and_garbage(self):
        for text in ("var other=[1];", "var searchData=[1,", "var searchData=[foo()]"):
            with self.assertRaises(DoxygenFormatError):
                js_value(text, "searchData")
```

- [ ] **Step 2: Run them to verify they fail** (import error: no `build_doxygen`).
- [ ] **Step 3: Implement `DoxygenFormatError` and `js_value`** as a small recursive-descent reader over the text after `var NAME =`. Integer object keys come back as strings.
- [ ] **Step 4: Run the tests to verify they pass.**
- [ ] **Step 5: Commit** `docshelf-build: Doxygen JS literal reader`.

### Task 2: `Source.file`

**Files:**
- Modify: `skills/docshelf-build/scripts/build_fetch.py` (class `Source`)
- Test: `tests/test_docshelf_build.py` (class `DoxygenSourceTests`)

**Interfaces:**
- Produces: `Source.file(self, rel: str) -> Optional[bytes]`: the body of
  `rel` (a path relative to the source base, e.g. `"search/searchdata.js"`).
  URL source: `_get` with the robots.txt check; 200 -> body; 404 or 410 ->
  `None`; robots.txt block -> `FetchError`; any other status ->
  `CLIError(code 4)` naming the URL and status. Local source: the file's
  bytes or `None` when missing; a path escaping the base -> `None`.

- [ ] **Step 1: Write the failing tests**: with `fake_opener`:
  `[(200, b"x")]` -> `b"x"`; `[(404, b"")]` -> `None`; `[(503, b"")]*4`
  (retries exhausted, `sleep=lambda s: None`) -> `CLIError` with
  `code == 4`; robots `"User-agent: *\nDisallow: /docs/search/"` ->
  `FetchError`. Local: `write(root, "search/searchdata.js", "v")` ->
  `b"v"`; `"nope.js"` -> `None`; `"../outside"` -> `None`.
- [ ] **Step 2: Run to verify they fail** (`AttributeError: file`).
- [ ] **Step 3: Implement `Source.file`.** Reuse `_get`/`_allowed` and the local path guard in `page`.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** `docshelf-build: Source.file for index files`.

### Task 3: Reader 1, the search index

**Files:**
- Modify: `skills/docshelf-build/scripts/build_doxygen.py`
- Test: `tests/test_docshelf_build.py` (class `DoxygenSearchIndexTests`)

**Interfaces:**
- Consumes: `js_value`, `DoxygenFormatError` (Task 1); a getter
  `get: Callable[[str], Optional[bytes]]` (in production `Source.file`).
- Produces:
  - `CATEGORY_ROLES: Dict[str, str]`: `classes` -> `doxygen:Class`,
    `namespaces` -> `doxygen:Namespace`, `files` -> `doxygen:File`,
    `functions` and `related` -> `doxygen:Function`, `variables` ->
    `doxygen:Variable`, `typedefs` -> `doxygen:Type`, `enums` ->
    `doxygen:Enum`, `enumvalues` -> `doxygen:Constant`, `defines` ->
    `doxygen:Macro`, `properties` -> `doxygen:Property`, `groups` ->
    `doxygen:Module`, `pages` -> `std:doc`. Any other name ->
    `doxygen:` + its `indexSectionLabels` text with spaces removed.
    A `classes` entry whose page uri starts with `struct` or `union` gets
    `doxygen:Struct` instead of `doxygen:Class` (Reader 2 the same).
  - `@dataclass DoxyIndex: kind: str ("search" | "menu"); entries:
    List[InvEntry]; files: List[Tuple[str, bytes]] (rel path, body, in read
    order, for hashing); warnings: List[str]`.
  - `read_search_index(get) -> DoxyIndex`.
  - `page_uri(url: str, base_rel: str) -> str`: resolves `url` against
    `base_rel` (`"search/"` here, `""` in Task 4) to a site-relative uri
    keeping `#anchor` (`"../group__window.html#ga5c"` -> 
    `"group__window.html#ga5c"`).
  - `member_name(display: str, scope: str, role: str, non_scopes: Set[str])
    -> Tuple[str, str]` -> `(name, dispname)` per the spec's naming rule:
    scope empty, in `non_scopes` (file names, group and page titles), or
    ending in a file extension (`\.\w{1,4}$`) -> `(display, "-")`; scope
    containing `(` or ending in `display` -> name is the scope with its
    trailing parameter list removed, dispname the scope; otherwise
    `(scope + "::" + display, "-")`. HTML entities decoded in both.
- Rules (spec "Reader 1"): read `search/searchdata.js`; for each category
  except `all`, file `search/<name>_<i>.js` for `i` in
  `range(len(letters))` written as lowercase hex (`format(i, "x")`); one
  `InvEntry(name, role, 1, uri, dispname)` per link; dedupe on
  `(name, role, uri)`; `std:doc` entries keep the display text as name.
  A file that is `None` or raises `DoxygenFormatError` -> a warning naming
  the file, continue. `searchdata.js` itself missing or unparseable, or no
  entries at all -> `DoxygenFormatError`.

- [ ] **Step 1: Write the failing tests** with an in-memory site
  `files = {rel: bytes}` and `get = files.get`:
  - fixture `searchdata.js` with categories
    `{0:"all",1:"classes",2:"files",3:"functions",4:"defines",5:"groups",6:"pages"}`,
    `functions` letters `"abcdefghijk"` (11 letters) and only
    `search/functions_0.js` and `search/functions_a.js` present;
  - `functions_a.js` holds `glfwKey` with link
    `['../group__input.html#ga1',1,'glfw3.h']` -> entry
    `InvEntry("glfwKey", "doxygen:Function", 1, "group__input.html#ga1", "-")`
    (pins hex naming, `../` resolution and bare C names);
  - an overload pair `['_get',['../a.html#x',1,'ns::A::_get()'],['../a.html#y',1,'ns::A::_get(int v)']]`
    -> two entries named `ns::A::_get`, dispnames `ns::A::_get()` and
    `ns::A::_get(int v)`;
  - a class `['Mat',['../classcv_1_1Mat.html',1,'cv']]` -> `cv::Mat`,
    `doxygen:Class`; `['GLFWimage',['../structGLFWimage.html',1,'']]`
    -> `GLFWimage`, `doxygen:Struct`;
  - the same member in `functions` and `all` -> one entry (`all_*` never
    requested: assert no requested rel starts with `search/all_`);
  - `&lt;`/`&amp;` in a signature decoded;
  - the 9 missing function files -> 9 warnings, entries still returned;
  - `functions_0.js` = `b"<html>blocked</html>"` -> a warning containing
    "blocking automated requests";
  - `searchdata.js` missing -> `DoxygenFormatError`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement `CATEGORY_ROLES`, `DoxyIndex`, `page_uri`, `member_name`, `read_search_index`.** `non_scopes` = names of `files` entries plus display names of `groups` and `pages` entries (read those categories first).
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** `docshelf-build: read Doxygen search indexes`.

### Task 4: Reader 2, `menudata.js` and index pages

**Files:**
- Modify: `skills/docshelf-build/scripts/build_doxygen.py`
- Test: `tests/test_docshelf_build.py` (class `DoxygenMenuIndexTests`)

**Interfaces:**
- Consumes: `js_value`, `DoxyIndex`, `page_uri`, `member_name` (Tasks 1, 3).
- Produces:
  - `MENU_PAGE_ROLES`: list-page stems `annotated` -> `doxygen:Class`,
    `namespaces` -> `doxygen:Namespace`, `files` -> `doxygen:File`,
    `modules`/`topics` -> `doxygen:Module`, `pages` -> `std:doc`; member
    tab suffixes `func` -> Function, `vars` -> Variable, `type` -> Type,
    `enum` -> Enum, `eval` -> Constant, `rela` -> Function, `prop` ->
    Property, `defs` -> Macro, applied to stems `functions`, `globals`,
    `namespacemembers`.
  - `menu_pages(menu: dict) -> List[Tuple[str, str]]`: `(rel, role)` for
    every menu URL (fragment dropped, deduped, in menu order) whose stem is
    in `MENU_PAGE_ROLES`, e.g. `globals_defs_e.html` -> Macro; untyped
    member pages (`functions.html`, `functions_a.html`) are skipped when
    the same stem has typed tabs.
  - `parse_list_page(html: str, role: str) -> List[InvEntry]`: every link
    inside `div.contents` whose target is a page of the site (not `#...`,
    not external), name = link text.
  - `parse_member_page(html: str, role: str, non_scopes: Set[str])
    -> List[InvEntry]`: inside `div.contents`, each `<li>` is
    `name : <a>Owner</a>[, <a>Owner2</a>]`; one entry per link, name from
    `member_name(text_before_colon, owner_link_text, role, non_scopes)`
    with the owner treated as the scope (`wxWindow` -> `wxWindow::SetSize`,
    `defs.h` -> bare). Letter headings and navigation ignored.
  - `read_menu_index(get) -> DoxyIndex`: `menudata.js` -> `menu_pages`;
    list pages first (they fill `non_scopes`), then member pages. If
    `menudata.js` is missing, use the fixed names `annotated.html`,
    `namespaces.html`, `files.html`, `modules.html`, `topics.html`,
    `pages.html`, `functions_<kind>.html`, `globals_<kind>.html`,
    `namespacemembers_<kind>.html` and follow per-letter links
    (`<stem>_<kind>_<letter>.html`) found in each page's `div.contents`
    letter bar. Before fetching, it prints (via a `log` callable argument,
    default `build_core.warn`) "reading N Doxygen index pages" once the
    menu gives N. Missing/failed pages -> warnings; no entries ->
    `DoxygenFormatError`.

- [ ] **Step 1: Write the failing tests** with hand-made HTML: an
  `annotated.html` with two classes; a `globals_defs.html` whose
  `div.contents` has letter links to `globals_defs_w.html` and an item
  `<li>wxUSE_X : <a class="el" href="defs_8h.html#a1">defs.h</a></li>`;
  a `functions_func_s.html` item
  `<li>SetSize() : <a class="el" href="classwx_window.html#a9">wxWindow</a>, <a class="el" href="classwx_frame.html#a3">wxFrame</a></li>`.
  Assert: `menu_pages` on a menudata dict with nested children returns
  `("globals_defs_e.html", "doxygen:Macro")` once (fragment dropped);
  `SetSize()` gives `wxWindow::SetSize` and `wxFrame::SetSize`, both
  `doxygen:Function`, uris `classwx_window.html#a9` / `classwx_frame.html#a3`;
  `wxUSE_X` is bare, `doxygen:Macro`; a page with navigation links outside
  `div.contents` contributes nothing from them; without `menudata.js` the
  fixed-name fallback finds the same entries; every page missing ->
  `DoxygenFormatError`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** with `html.parser` (stdlib), as in `build_html.py`. The member-name text drops a trailing `()`.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Commit** `docshelf-build: read Doxygen menu and index pages`.

### Task 5: Site header, `read_doxygen` and the plan rule

**Files:**
- Modify: `skills/docshelf-build/scripts/build_doxygen.py`,
  `skills/docshelf-build/scripts/build_plan.py`
- Test: `tests/test_docshelf_build.py` (class `DoxygenPlanTests`)

**Interfaces:**
- Consumes: `read_search_index`, `read_menu_index`, `DoxyIndex`.
- Produces:
  - `site_header(front_html: str) -> dict`: `{"project", "version",
    "doxygen"}` from `#projectname` text (first text node), `#projectnumber`
    (a leading `Version:` stripped), the `Generated by Doxygen X.Y.Z`
    comment; `project` falls back to `<title>` text before ` | ` or ` - `.
  - `read_doxygen(get) -> Tuple[str, dict, List[InvEntry], DoxyIndex]`:
    search index when `search/searchdata.js` exists, else the menu reader;
    when the search reader raises `DoxygenFormatError` (an unsupported
    older format, e.g. Doxygen 1.8's `all_61.js` naming) and `menudata.js`
    exists, a warning "search index not readable (...), using the index
    pages" and the menu reader;
    `sha256` over `rel + "\0" + body` of `DoxyIndex.files` in order;
    header from `index.html` (missing -> `{"project": "", "version": "",
    "doxygen": ""}`); warnings printed by the caller.
  - `dropped_page(uri: str) -> bool`: true for the index pages of Task 4,
    `*_8md.html`, `*_8dox.html`, `*_8txt.html`, `dir_*.html`,
    `*_source.html`, `graph_legend.html`, `deprecated.html`, `todo.html`,
    `bug.html`, `test.html`, `index.html` is **kept**.
  - `make_plan(..., kind: str = "sphinx")` in `build_plan.py`: with
    `kind="doxygen"`: pages where `dropped_page` is true are skipped; a
    page is `("full", "roles: <sorted domain roles>")` when it has any role
    outside `{doxygen:File, doxygen:Module, doxygen:Namespace, std:doc}`,
    else `("stub", "roles: headings only")`; title = name of the page's
    anchorless entry (Class/Struct/File/Module/Namespace/std:doc), else the
    key; `section` = None; plan `"kind": "doxygen"`, `"rule":
    "doxygen-members"`. Sphinx behaviour unchanged.
  - `summarize` for a doxygen plan adds `index: search|menu` and the entry
    count per type (largest first).

- [ ] **Step 1: Write the failing tests:** `site_header` on
  `<div id="projectname">GLFW<span id="projectnumber">&#160;3.4.0</span></div>`
  -> project "GLFW", version "3.4.0"; on `<span id="projectnumber">Version: 3.2.13</span>`
  -> "3.2.13"; Doxygen version from `<!-- Generated by Doxygen 1.9.1 -->`.
  `make_plan(kind="doxygen")` on entries: a group page with a Function ->
  full; a file page with only its File entry -> stub; a page with only
  `std:doc` -> stub; `main_8md.html` and `dir_abc.html` -> absent; a class
  page with only its Class entry -> full; `--stub 'group__*'` override
  wins. `read_doxygen` picks the search reader when both index kinds exist
  and gives the same sha for the same files; with an unparseable
  `searchdata.js` plus `menudata.js` it warns and returns `index: menu`.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Keep `make_plan`'s override/`_choose` logic shared; the kind only swaps the page rule, the filter and titles.
- [ ] **Step 4: Run, plus the existing `PlanTests`, to verify they pass.**
- [ ] **Step 5: Commit** `docshelf-build: Doxygen plan rule`.

### Task 6: Doxygen page content

**Files:**
- Modify: `skills/docshelf-build/scripts/build_html.py` (`main_content`)
- Test: `tests/test_docshelf_build.py` (class `DoxygenHtmlTests`)

**Interfaces:**
- Produces: `main_content(page_html)` returns, for a page with a
  `div.contents`, the `div.headertitle` (if any) followed by the
  `div.contents`, with removed: `div.dynheader`/`div.dyncontent` (graphs),
  `map`, `div.ttc`, `a` elements whose text is `More...`, `div.navpath`,
  `script`. Other pages unchanged (existing selectors).

- [ ] **Step 1: Write the failing tests** on a hand-made page: `div#top`
  menu + `div#side-nav` tree + search box + `div.header` (with
  `div.headertitle` "Window reference") + `div.contents` holding a
  collaboration graph `div.dynheader`/`div.dyncontent` with `<map>`, a
  `<a href="#details">More...</a>`, and a member:
  `<a id="ga5c"></a><h2 class="memtitle">glfwCreateWindow()</h2><div class="memitem"><div class="memproto">GLFWwindow * glfwCreateWindow (int width)</div><div class="memdoc">Creates a window.</div></div>`,
  then `<hr class="footer"/><address class="footer">Generated by doxygen</address>`.
  Assert the output contains "Window reference", `id="ga5c"`,
  "glfwCreateWindow (int width)", "Creates a window."; and does not
  contain "More...", "<map", the menu text, the tree text, "Generated by".
  A doxygen-awesome variant (extra `div` wrappers around
  `div.header`/`div.contents`) gives the same text. A Sphinx page from the
  existing tests is unchanged.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** a Doxygen branch checked before `_SELECTORS`.
- [ ] **Step 4: Run, plus the existing `HtmlTests`, to verify they pass.**
- [ ] **Step 5: Commit** `docshelf-build: Doxygen page content`.

### Task 7: detect, plan and build from the CLI

**Files:**
- Modify: `skills/docshelf-build/scripts/build_detect.py`,
  `skills/docshelf-build/scripts/docshelf_build.py`
- Test: `tests/test_docshelf_build.py` (class `DoxygenCliTests`)

**Interfaces:**
- Consumes: `Source.file`, `read_doxygen`, `make_plan(kind=...)`,
  `summarize`.
- Produces:
  - `DOCS["doxygen"] = "BUILD-doxygen.md"`; `detect` tries Doxygen after
    Sphinx and llms.txt: in the given folder (a page URL's folder, a base
    with or without trailing `/`), then its parent once, request
    `search/searchdata.js` (contains `indexSectionNames`) then
    `menudata.js` (contains `var menudata`). `Detection.kind = "doxygen"`,
    `source` = that folder (URL with trailing `/`, or local path);
    `describe` adds `index: search` or `index: menu`; other found types
    stay `also:` lines. The not-found message becomes "no objects.inv,
    llms.txt or Doxygen index found".
  - `do_plan`: when the source has no `objects.inv` (`Source.file` returns
    `None`) and has a Doxygen index, read it with `read_doxygen`, print
    each warning with `warn`, name = `args.name or derive_name(header)`,
    `make_plan(..., kind="doxygen")` with `plan["index"]` and
    `plan["doxygen"]` added, no archive lookup. Neither -> `CLIError(code
    3)` "no objects.inv or Doxygen index in SOURCE".
  - `do_build`: for `plan["kind"] == "doxygen"`, re-read with
    `read_doxygen`, re-plan with `kind="doxygen"` on a changed sha, never
    use an archive, then the same fetch/write/summary as Sphinx.
  - `_read_inventory` stays Sphinx-only.

- [ ] **Step 1: Write the failing tests** with a local fixture folder
  (written with `write`) holding `index.html` (projectname "Demo",
  projectnumber "1.2"), `search/searchdata.js`, `search/functions_0.js`,
  `search/pages_0.js`, `group__demo.html` (a member page) and
  `guide.html` (prose): `detect` -> `type: doxygen`, `index: search`,
  `read: BUILD-doxygen.md`; `detect` on `<folder>/group__demo.html` finds
  the same source; a folder with both `objects.inv` and Doxygen files ->
  `type: sphinx`, `also: doxygen`; `main(["build", folder, "--name",
  "demo"])` exits 0, the docvol's `index.json` has a `Function` entry at
  `group__demo#<anchor>` and `db.json` has `group__demo` in full and
  `guide` as a stub; a second tree with only `menudata.js` and
  `globals_func.html` builds the same way with `index: menu`; an empty
  folder -> exit 3. Rebuild with `main(["build", "demo"])` after adding a
  function file reports the inventory change and re-plans.
- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole file to verify everything passes:**
  `python3 -m unittest discover -s tests -p test_docshelf_build.py`.
- [ ] **Step 5: Commit** `docshelf-build: doxygen site type in detect, plan and build`.

### Task 8: Docs, version and notes

**Files:**
- Create: `skills/docshelf-build/BUILD-doxygen.md`
- Modify: `skills/docshelf-build/SKILL.md`, `scripts/build_core.py`,
  `AGENTS.md` (docshelf-build entry), `TODO.md` (8.4 and a new item)

**Interfaces:** none (docs).

- [ ] **Step 1: `BUILD-doxygen.md`** in `BUILD-sphinx.md`'s shape: what sites (Doxygen HTML; Breathe sites are `sphinx`), the two index kinds and what `plan` prints, the loop (`plan` -> check types/pages -> `build`), the page rule (member pages full, prose stubs, junk dropped), overrides (`--full 'group__*'`, `--stub`), component sites as separate docvols (`--name cmsis-core`), blocked-requests error, exit codes. Examples use `https://docs.example.org/api/`.
- [ ] **Step 2: `SKILL.md`**: description adds "or a Doxygen HTML site (C/C++ API references such as GLFW or wxWidgets)" and stays one line starting "Use when"; section 2 gains a **doxygen** bullet linking `BUILD-doxygen.md`; `metadata.version: "0.5.0"`.
- [ ] **Step 3: `build_core.py`** `VERSION = "0.5.0"`.
- [ ] **Step 4: Notes:** AGENTS.md docshelf-build entry gets a 0.5.0 sentence (the `doxygen` type, both readers, the page rule, the user's 2026-11-23 decisions: one docvol per component, Pico out of scope, trials gate the merge); TODO.md 8.4 reworded to "Doxygen HTML sites" and ticked only after Task 9, plus a new open item "Doxygen tagfiles and XML (local builds)".
- [ ] **Step 5: Verify:** full suite `python3 -m unittest discover -s tests` passes (includes `test_skills.py` version and link checks, `test_public_safety.py`); `python3 scripts/ci_changed_skills.py --base origin/main --check-versions` passes.
- [ ] **Step 6: Commit and push** `docshelf-build 0.5.0: Doxygen sites`; push `update/docshelf-build`; then subscribe to PR #38's activity (the user: watch only once it has code).

### Task 9: Real-site trials (gate for leaving draft)

**Files:**
- Create: `docs/trials/2026-11-23-docshelf-build-doxygen/README.md` (results only; no copied site content beyond short quoted entry names)

**Interfaces:** none.

- [ ] **Step 1: GLFW**, with a throwaway `DOCSHELF_CACHE_DIR` in the scratchpad: `detect https://www.glfw.org/docs/latest/` -> `type: doxygen`, `index: search`; `build https://www.glfw.org/docs/latest/ --name glfw`; then docshelf `search glfwCreateWindow -d glfw`, `show` it (lands on the member), `search GLFWwindow`, `search GLFW_KEY_ESCAPE` (Macro), and a guide page (e.g. `window_guide`) is a stub.
- [ ] **Step 2: wxWidgets**: `detect https://docs.wxwidgets.org/3.2/` -> `index: menu`; build `--name wxwidgets`; check `wxWindow::SetSize` (Function, lands on the member), a global function, a macro (`wxUSE_*`), an enum value (Constant); note the index-page request count and total time.
- [ ] **Step 3: Record** for each: entries per type, full/stub/failed counts, warnings, request count, time, spot-check results, any fixes needed. A failure goes back to the owning task as a test + fix before continuing.
- [ ] **Step 4: Commit and push** the trial notes; tick TODO 8.4; mark PR #38 ready for review only when both sites pass, and tell the user.
