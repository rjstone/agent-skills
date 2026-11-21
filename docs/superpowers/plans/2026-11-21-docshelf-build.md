# docshelf-build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new skill `docshelf-build` that turns a Sphinx site (anything with
`objects.inv`) into a trimmed, DevDocs-shaped docvol, plus a docshelf update
that lists such built docvols and protects them from `install`/`update`.

**Architecture:** `docshelf-build` is standalone (it cannot import docshelf):
it parses `objects.inv`, writes an editable plan (`full`/`stub` per page),
fetches the `full` pages, cleans them, and writes `index.json`, `db.json`,
`meta.json` under `<cache>/built/<name>/`. docshelf gains a `BuiltDocvol`
backend that reuses its DevDocs reader on that folder.

**Tech Stack:** Python 3 standard library only (`zlib`, `urllib`,
`urllib.robotparser`, `html.parser`, `fnmatch`, `json`), `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-21-docshelf-build-design.md`
(approved by the user on PR #29, 2026-11-21).

## Global Constraints

- Standard library only; no install step.
- Two branches: Part A on `update/docshelf` (own PR, merge commit, docshelf
  `metadata.version` and `shelf_core.VERSION` `"0.8.2"` -> `"0.9.0"`);
  Part B on `skill/docshelf-build` (PR #29, squash-merge), skill version
  `"0.1.0"`.
- Cache root: `DOCSHELF_CACHE_DIR`, else `%LOCALAPPDATA%\docshelf\cache`
  on Windows, else `~/.cache/docshelf` (copy of docshelf's
  `shelf_core._default_cache`; `.docshelf.json` never sets it).
- Built docvol: `<cache>/built/<name>/{index.json, db.json, meta.json}`.
  Plan: `<cache>/built-plans/<name>.json`.
- `index.json` = `{"entries": [{"name", "type", "path"}], "types":
  [{"name", "count", "slug"}]}`; `db.json` = `{page_key: html}`;
  `meta.json` = `{"slug", "name", "release", "version", "mtime",
  "installedAt", "alias": null, "entry_count", "origin":
  "docshelf-build", "source", "inventory_sha256"}`. `mtime` = build time
  (epoch seconds): docshelf's derived indexes are keyed on it.
- Names match docshelf's `SLUG_RE` `^[a-z0-9][a-z0-9._~+-]*$` (case-
  insensitive).
- HTTP: `User-Agent: docshelf-build/<VERSION>`; 1 worker default, max 4;
  `0.5` s delay between requests per worker; honour `robots.txt`; retry
  429/5xx 3 times with backoff 1, 2, 4 s.
- Tests: no network; `tests/test_docshelf_build.py` starts with the
  `selected("docshelf-build")` skip guard; `VERSION = "0.1.0"` lives only
  in `scripts/build_core.py` and tests read it from there.
- Public repo rules (AGENTS.md): no machine paths or names; run
  `tests/test_public_safety.py` and read the diff before each commit.

## Review Focus

1. **A site where no page has a domain role** (SpinalHDL-like, all
   `std:*`): the plan must not silently yield an empty docvol; `plan`
   prints a warning naming the biggest page groups and suggesting
   `--full 'group/*'`. Test in Task 3.
2. **Links**: relative (`../x.html#a`), directory-style (`../x/`), to a
   stub page, and to another site. Internal ones must resolve in docshelf;
   external ones stay absolute. Tests in Task 5.
3. **A failed or interrupted build** must leave the previous docvol
   readable; a page that 404s after retries becomes a stub with the error,
   and the build exits 0 with a count of failed pages. Tests in Task 6.
4. **robots.txt** disallowing a page makes it a stub ("blocked by
   robots.txt"); a missing robots.txt (404) allows everything. Test in
   Task 4.
5. **Source given as `.../index.html`, without a trailing slash, or as a
   local folder path**: all normalise to the same base. Test in Task 4.

---

## Part A: docshelf (`update/docshelf`)

### Task 1: docshelf reads and protects built docvols

**Files:**
- Modify: `skills/docshelf/scripts/shelf_devdocs.py` (add `built_dir`,
  `BuiltDocvol`, `installed_built`; refusals in `cmd_install`,
  `cmd_update`, `cmd_remove`)
- Modify: `skills/docshelf/scripts/shelf_backends.py` (`installed_docvols`)
- Modify: `skills/docshelf/scripts/shelf_core.py` (`VERSION = "0.9.0"`,
  `source` comment adds `"built"`)
- Modify: `skills/docshelf/SKILL.md` (version `"0.9.0"`; one line: built
  docvols come from the `docshelf-build` skill and are rebuilt there)
- Test: `tests/test_docshelf.py` (new class `BuiltDocvolTest`)

**Interfaces:**
- Produces: `built_dir(cfg) -> str` (`<cache>/built`);
  `class BuiltDocvol(DevDocsDocvol)` with `source = "built"`,
  `read_only = False`, repair hint `"rebuild with: docshelf-build build
  NAME"`; `installed_built(cfg) -> List[BuiltDocvol]`.
- Consumes: existing `DevDocsDocvol`, `make_devdocs` test helper.

- [ ] **Step 1: Write the failing tests** (helper `make_built(cache, name,
  ...)` = `make_devdocs` writing under `built/` with `"origin":
  "docshelf-build"` in `meta.json`)

```python
def test_built_docvol_is_listed_and_searchable(self):
    make_built(self.cache, "yosys", entries=[("opt", "cmd", "cmd/opt#opt")],
               pages={"cmd/opt": "<h1 id=opt>opt</h1>"})
    r = run(["list"]); assert "yosys" in r.stdout and "built" in r.stdout
    r = run(["search", "opt", "-d", "yosys"]); assert "yosys:cmd/opt#opt" in r.stdout

def test_install_refuses_built_name(self):   # exit code 2
    make_built(self.cache, "yosys", ...); make manifest row slug "yosys"
    r = run(["install", "yosys"]); assert r.returncode == 2
    assert "docshelf-build" in r.stderr

def test_update_skips_built_silently_and_refuses_by_name(self):
    r = run(["update"]); assert "yosys" not in r.stderr
    r = run(["update", "yosys"]); assert r.returncode == 2 and "docshelf-build" in r.stderr

def test_built_wins_name_clash_with_warning(self):
    make_devdocs(self.cache, "yosys", ...); make_built(self.cache, "yosys", ...)
    r = run(["list"]); assert r.stdout.count("yosys") == 1
    assert "built" in r.stdout and "same name" in r.stderr

def test_remove_removes_built(self):
    r = run(["remove", "yosys"]); assert r.returncode == 0
    assert not os.path.exists(os.path.join(self.cache, "built", "yosys"))
```

- [ ] **Step 2: Run, expect FAIL**: `python3 -m unittest tests.test_docshelf.BuiltDocvolTest -v`
- [ ] **Step 3: Implement.** `installed_docvols`: built first, then DevDocs
  (skip a DevDocs one whose name is built, warning "skipping DevDocs docvol
  NAME: a built docvol has the same name"), then docsets as today.
  `cmd_install`: refuse (code 2) a name in `installed_built`. `cmd_update`:
  targets exclude `source == "built"`; a named built one -> code 2.
  `remove`: delete from `built_dir` when the docvol is built (the plan file
  stays; say so: "plan kept: <path>"). `list` shows `built` where it shows
  the source today.
- [ ] **Step 4: Run the whole docshelf suite, expect PASS**: `python3 -m unittest tests.test_docshelf tests.test_skills -v`
- [ ] **Step 5: Commit, push, open PR** (`update/docshelf`, template
  "Skill update", bump rule "minor: new feature"); add the CLAUDE.md
  fetch-refspec line before the first push.

---

## Part B: docshelf-build (`skill/docshelf-build`)

Script files, all in `skills/docshelf-build/scripts/`:

| File | Responsibility |
|---|---|
| `build_core.py` | `VERSION`, `CLIError(msg, code)`, `warn`, `cache_dir(env)`, `built_dir`, `plans_dir`, `NAME_RE` |
| `build_inventory.py` | parse `objects.inv`; page keys |
| `build_plan.py` | role rule, overrides, merge, load/save, summary |
| `build_fetch.py` | sources (URL or folder), robots, retries |
| `build_html.py` | main-content extraction, link rewriting, stub HTML |
| `build_docvol.py` | name checks, index/db/meta writing, atomic replace |
| `docshelf_build.py` | argparse CLI: `plan`, `build`, `list`, `remove` |

### Task 2: Inventory parsing and page keys

**Files:**
- Create: `skills/docshelf-build/scripts/build_core.py`, `build_inventory.py`
- Test: `tests/test_docshelf_build.py` (guard + helper `make_inv(entries,
  project="Demo", version="1.0") -> bytes` that writes a v2 inventory with
  `zlib`)

**Interfaces:**
- Produces: `@dataclass(frozen=True) InvEntry(name: str, role: str,
  priority: int, uri: str, dispname: str)` where `uri` has `$` already
  expanded; `parse_inventory(data: bytes) -> Tuple[dict, List[InvEntry]]`
  (header dict: `project`, `version`); `split_uri(uri) -> Tuple[str,
  Optional[str]]` (page uri, anchor); `page_key(page_uri: str) -> str`.

- [ ] **Step 1: Failing tests**

```python
def test_parse_expands_dollar_and_keeps_dash_dispname(self):
    hdr, es = parse_inventory(make_inv([("opt", "cmd:cmd", "1", "cmd/opt.html#$", "-")]))
    assert hdr == {"project": "Demo", "version": "1.0"}
    assert es[0].uri == "cmd/opt.html#opt" and es[0].dispname == "-"

def test_names_with_spaces(self):  # std:label names may hold spaces
    _, es = parse_inventory(make_inv([("my label", "std:label", "-1", "a.html#x", "My Label")]))
    assert es[0].name == "my label" and es[0].priority == -1

def test_page_keys(self):
    assert page_key("cmd/opt.html") == "cmd/opt"
    assert page_key("api/foo/") == "api/foo"
    assert page_key("") == "index" and page_key("index.html") == "index"

def test_rejects_v1_and_garbage(self):  # CLIError code 3, message names the problem
    with self.assertRaises(CLIError): parse_inventory(b"# Sphinx inventory version 1\n")
    with self.assertRaises(CLIError): parse_inventory(b"<html>not found</html>")
```

- [ ] **Step 2: Run, expect FAIL** (`python3 -m unittest tests.test_docshelf_build -v`)
- [ ] **Step 3: Implement.** Line regex (Sphinx's own):
  `(.+?)\s+(\S+)\s+(-?\d+)?\s*(\S*)\s+(.*)`; `$` at the end of `uri`
  is replaced with `name`. `cache_dir` copies docshelf's rules (Global
  Constraints). `VERSION = "0.1.0"`.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `docshelf-build: inventory parsing`

### Task 3: Plan (rule, overrides, merge, summary)

**Files:**
- Create: `skills/docshelf-build/scripts/build_plan.py`
- Test: `tests/test_docshelf_build.py`

**Interfaces:**
- Consumes: `InvEntry`, `split_uri`, `page_key` (Task 2).
- Produces: `make_plan(source: str, inv_sha256: str, header: dict,
  entries: List[InvEntry], overrides: List[Tuple[str, str]], old:
  Optional[dict] = None, reset: bool = False, base_url: Optional[str] =
  None) -> dict` (the spec's plan JSON, `"format": 1`, page keys from
  `page_key`, each page also carries `"uri"`; top-level `"base_url"`: the
  live base for stubs and external links = the source when it is a URL,
  else `base_url` (kept from `old` when not given), else `null`); `load_plan(path) -> dict`; `save_plan(path, plan)` (atomic);
  `summarize(plan, old: Optional[dict]) -> List[str]`.

- [ ] **Step 1: Failing tests**

```python
def test_role_rule(self):
    p = make_plan(SRC, "h", HDR, ENTRIES, [])  # cmd/opt has cmd:cmd; guide/a only std:*
    assert p["pages"]["cmd/opt"]["keep"] == "full"
    assert p["pages"]["guide/a"]["keep"] == "stub"
    assert p["pages"]["guide/a"]["why"] == "roles: std only"

def test_overrides_last_wins_and_append(self):
    p = make_plan(SRC, "h", HDR, ENTRIES, [("full", "guide/*")])
    p = make_plan(SRC, "h", HDR, ENTRIES, [("stub", "guide/a")], old=p)
    assert p["overrides"] == [["full", "guide/*"], ["stub", "guide/a"]]
    assert p["pages"]["guide/a"]["keep"] == "stub"
    assert p["pages"]["guide/b"]["why"] == "override: guide/*"

def test_reset_and_all(self):
    p = make_plan(SRC, "h", HDR, ENTRIES, [("full", "*")])
    assert all(v["keep"] == "full" for v in p["pages"].values())
    p = make_plan(SRC, "h", HDR, ENTRIES, [], old=p, reset=True)
    assert p["overrides"] == []

def test_manual_beats_override_and_survives(self):
    p = make_plan(SRC, "h", HDR, ENTRIES, [])
    p["pages"]["guide/a"].update(keep="full", why="manual")
    p = make_plan(SRC, "h2", HDR, ENTRIES, [("stub", "guide/*")], old=p)
    assert p["pages"]["guide/a"]["keep"] == "full"

def test_inventory_change_adds_and_drops(self):
    p = make_plan(SRC, "h", HDR, ENTRIES, [])
    p = make_plan(SRC, "h2", HDR, ENTRIES_WITHOUT_GUIDE_A_PLUS_NEW_C, [], old=p)
    assert "guide/a" not in p["pages"] and "cmd/c" in p["pages"]
    lines = summarize(p, old)
    assert any("added 1" in l for l in lines) and any("dropped 1" in l for l in lines)

def test_titles_and_sections(self):  # title from std:doc dispname; section from <dir>/index title
    assert p["pages"]["guide/a"]["title"] == "Guide A"
    assert p["pages"]["guide/a"]["section"] == "Guides"

def test_all_stub_warning(self):  # Review Focus 1
    lines = summarize(make_plan(SRC, "h", HDR, STD_ONLY_ENTRIES, []), None)
    assert any("no page has a domain role" in l and "--full 'guide/*'" in l for l in lines)
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement.** Precedence: `manual` > last matching override
  (`fnmatch.fnmatchcase` on the page key) > role rule. A page is `full` by
  the rule when any of its entries' role does not start with `std:`.
  `section`: title of `<first dir>/index` if present, else the first path
  component; `None` for top-level pages. Summary: full/stub page counts,
  entry count, the five largest first-directory groups with their
  full/stub split; the all-stub warning names the largest group.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `docshelf-build: plan file`

### Task 4: Sources and fetching

**Files:**
- Create: `skills/docshelf-build/scripts/build_fetch.py`
- Test: `tests/test_docshelf_build.py`

**Interfaces:**
- Produces: `normalize_source(src: str) -> Tuple[str, bool]` (base URL
  ending in `/` or absolute folder path; `True` if URL);
  `class Source` with `inventory() -> bytes`, `page(uri: str) -> str`
  (raises `FetchError(uri, reason)`), `live_url(uri) -> Optional[str]`;
  `open_source(src, base_url=None, workers=1, delay=0.5, opener=None)
  -> Source`; `fetch_pages(source, uris: List[str]) -> Tuple[Dict[str,
  str], Dict[str, str]]` (html by uri, error reason by uri).
- `opener` is the test seam: a callable `(url) -> (status, bytes)`; the
  default uses `urllib.request` with the `User-Agent` header.

- [ ] **Step 1: Failing tests**

```python
def test_normalize_source(self):  # Review Focus 5
    for s in ("https://x.io/docs", "https://x.io/docs/", "https://x.io/docs/index.html"):
        assert normalize_source(s) == ("https://x.io/docs/", True)
    assert normalize_source(self.tmp)[0] == os.path.abspath(self.tmp)

def test_local_folder_reads_dir_uris(self):
    write(self.tmp, "api/foo/index.html", "<p>x</p>")
    assert "x" in open_source(self.tmp).page("api/foo/")

def test_user_agent_and_retries(self):
    calls = fake_opener([(503, b""), (503, b""), (200, b"<p>ok</p>")])
    html, errs = fetch_pages(open_source(URL, opener=calls, delay=0), ["a.html"])
    assert html["a.html"] == "<p>ok</p>" and not errs
    # with the default opener: Request headers carry "docshelf-build/" + VERSION (mock urlopen)

def test_404_becomes_error_not_exception(self):
    html, errs = fetch_pages(open_source(URL, opener=fake_opener([(404, b"")] * 4), delay=0), ["a.html"])
    assert errs == {"a.html": "HTTP 404"}

def test_robots(self):  # Review Focus 4
    src = open_source(URL, opener=robots_opener("User-agent: *\nDisallow: /docs/private/"), delay=0)
    _, errs = fetch_pages(src, ["private/a.html", "b.html"])
    assert errs == {"private/a.html": "blocked by robots.txt"}
    src = open_source(URL, opener=robots_opener(None), delay=0)  # robots.txt 404
    assert fetch_pages(src, ["private/a.html"])[1] == {}
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement.** robots.txt fetched once via the same opener and
  fed to `urllib.robotparser.RobotFileParser.parse`; retries only on 429
  and 5xx (Global Constraints values; `sleep` injectable). Workers: a
  `ThreadPoolExecutor(max_workers=min(workers, 4))`.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `docshelf-build: sources and fetching`

### Task 5: HTML cleaning, links, stubs

**Files:**
- Create: `skills/docshelf-build/scripts/build_html.py`
- Test: `tests/test_docshelf_build.py`

**Interfaces:**
- Produces: `main_content(html: str) -> str`; `rewrite_links(html: str,
  page_key: str, page_uri: str, keys_by_uri: Dict[str, str], live_base:
  Optional[str]) -> str`; `stub_html(title: str, section: Optional[str],
  description: Optional[str], url: Optional[str], note: Optional[str])
  -> str`.

- [ ] **Step 1: Failing tests**

```python
def test_main_content_drops_chrome(self):
    out = main_content(SPHINX_PAGE)  # nav, sidebar, <script>, <style>, footer around div[role=main]
    assert "Sidebar" not in out and "<script" not in out and "Real text" in out

def test_main_content_fallbacks(self):  # selector order: [role=main], main, article, div.body, body
    assert "T" in main_content("<html><body><main><p>T</p></main></body></html>")

def test_rewrite_links(self):  # Review Focus 2
    keys = {"cmd/opt.html": "cmd/opt", "using/x.html": "using/x", "api/foo/": "api/foo"}
    out = rewrite_links(HTML_WITH_LINKS, "cmd/opt", "cmd/opt.html", keys, "https://x.io/docs/")
    assert 'href="../using/x#sec"' in out       # ../using/x.html#sec
    assert 'href="../api/foo"' in out           # ../api/foo/
    assert 'href="#local"' in out               # same-page anchor kept
    assert 'href="https://other.org/p"' in out  # external kept
    assert 'href="https://x.io/docs/missing.html"' in out  # not in keys -> live URL

def test_stub_html(self):
    h = stub_html("Install", "Getting started", None, "https://x.io/docs/i.html", None)
    assert "Install" in h and "Not stored; read it at" in h and 'href="https://x.io/docs/i.html"' in h
    h = stub_html("A", None, None, None, "left out of the build (source: guide/a.html)")
    assert "left out of the build" in h
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement** with `html.parser.HTMLParser` (no regex HTML
  surgery). A link's target is `urljoin("http://h/" + page_uri, href)`
  mapped back to a uri; a key in `keys_by_uri` becomes a path relative to
  `posixpath.dirname(page_key)` (docshelf resolves hrefs against the page
  key). `<img>` becomes its `alt` text.
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `docshelf-build: HTML cleaning and links`

### Task 6: Writing the docvol

**Files:**
- Create: `skills/docshelf-build/scripts/build_docvol.py`
- Test: `tests/test_docshelf_build.py`

**Interfaces:**
- Consumes: plan dict (Task 3), `fetch_pages` result (Task 4),
  `main_content`/`rewrite_links`/`stub_html` (Task 5).
- Produces: `derive_name(header: dict) -> str`; `check_name(cache: str,
  name: str) -> None` (CLIError code 2); `role_label(role: str) -> str`;
  `write_docvol(cache: str, name: str, plan: dict, entries:
  List[InvEntry], pages_html: Dict[str, str], errors: Dict[str, str],
  now: float) -> dict` (returns `meta`). `pages_html` and `errors` are
  keyed by inventory page uri, as `fetch_pages` returns them; links and
  stub URLs use `plan["base_url"]`.

- [ ] **Step 1: Failing tests**

```python
def test_derive_and_check_name(self):
    assert derive_name({"project": "YosysHQ Yosys", "version": ""}) == "yosyshq-yosys"
    assert derive_name({"project": "SpinalHDL", "version": "master"}) == "spinalhdl~master"
    write_manifest(self.cache, ["python~3.12"])
    with self.assertRaises(CLIError) as c: check_name(self.cache, "python~3.12")
    assert "docshelf install python~3.12" in str(c.exception)
    with self.assertRaises(CLIError): check_name(self.cache, "../x")

def test_role_labels(self):
    assert [role_label(r) for r in ("py:function", "cmd:cmd", "std:doc", "std:label", "std:term")] \
        == ["function", "cmd", "Page", "Section", "Term"]

def test_write_docvol_shape(self):
    meta = write_docvol(self.cache, "demo", PLAN, ENTRIES, HTML, {}, now=1800000000)
    d = os.path.join(self.cache, "built", "demo")
    idx = load(d, "index.json"); db = load(d, "db.json")
    assert {"name": "opt", "type": "cmd", "path": "cmd/opt#opt"} in idx["entries"]
    assert {"name": "Guide A", "type": "Guide", "path": "guide/a"} in idx["entries"]
    assert not any(e["path"].startswith("guide/a#") for e in idx["entries"])  # stub: one entry only
    assert "Not stored" in db["guide/a"]
    assert meta["mtime"] == 1800000000 and meta["origin"] == "docshelf-build"
    assert meta["entry_count"] == len(idx["entries"])

def test_std_label_with_dash_dispname_skipped(self): ...  # anonymous labels add noise

def test_failed_page_becomes_stub(self):  # Review Focus 3
    write_docvol(self.cache, "demo", PLAN, ENTRIES, {}, {"cmd/opt.html": "HTTP 404"}, now=1)
    assert "HTTP 404" in load(..., "db.json")["cmd/opt"]

def test_failed_write_keeps_previous(self):  # Review Focus 3
    write_docvol(...first...)
    with mock.patch("os.replace", side_effect=[None, OSError("disk full")]):
        with self.assertRaises(CLIError): write_docvol(...second...)
    # previous index.json/db.json/meta.json all still the first build's
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement.** Names: lowercase, runs of characters outside
  `[a-z0-9.+-]` -> `-`, trimmed; `~version` appended when version is
  non-empty. `check_name`: `NAME_RE`, then refuse if `<cache>/devdocs/<name>`
  exists or `<cache>/devdocs/docs.json` has that `slug`. Atomic replace:
  write all three to temp files in the folder; replace `meta.json` **last**
  and only after the other two; on any failure restore from `.bak` copies
  made before the first replace (so docshelf never sees a new
  `db.json` with an old `meta.json` and stale `mtime`).
- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** `docshelf-build: docvol writer`

### Task 7: CLI, end to end, SKILL.md

**Files:**
- Create: `skills/docshelf-build/scripts/docshelf_build.py`,
  `skills/docshelf-build/SKILL.md`
- Modify: `AGENTS.md` (Skills list: one `docshelf-build` entry);
  `TODO.md` on `main` is not touched here
- Test: `tests/test_docshelf_build.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: List[str], env=None) -> int`. Commands:
  `plan SOURCE [--name N] [--full PAT]... [--stub PAT]... [--all]
  [--reset] [--base-url URL]`; `build NAME [--workers N]`;
  `build SOURCE [plan options] [--workers N]` (SOURCE contains `/` or
  `:` or is an existing folder -> treated as a source); `list`;
  `remove NAME [--plan]` (keeps the plan unless `--plan`); `--version`.
  Exit codes: 0 ok, 2 usage/name, 3 bad inventory, 4 network.

- [ ] **Step 1: Failing tests** (end to end on a local Sphinx-like
  folder: `objects.inv` from `make_inv` + three pages)

```python
def test_plan_then_build_then_docshelf_reads_it(self):
    assert main(["plan", self.site, "--name", "demo"], env=self.env) == 0
    assert os.path.isfile(os.path.join(self.cache, "built-plans", "demo.json"))
    assert main(["build", "demo"], env=self.env) == 0
    # docshelf (Part A merged or on PYTHONPATH from the branch) reads it:
    r = run_docshelf(["search", "opt", "-d", "demo"], env=self.env)
    assert "demo:cmd/opt#opt" in r.stdout
    r = run_docshelf(["show", "demo:guide/a"], env=self.env)
    assert "left out of the build" in r.stdout

def test_build_source_in_one_step_and_rebuild(self):
    assert main(["build", self.site, "--name", "demo", "--full", "guide/*"], env=self.env) == 0
    assert main(["build", "demo"], env=self.env) == 0  # reuses plan; meta.mtime changes

def test_list_and_remove(self):
    ...; assert main(["remove", "demo"], env=self.env) == 0
    assert os.path.isfile(plan_path) and not os.path.isdir(docvol_path)

def test_version_matches_core(self):
    out = capture(main, ["--version"]); assert build_core.VERSION in out
```

  The docshelf half of the first test is skipped (with a reason) when
  docshelf has no `BuiltDocvol` yet, so Part B can land before Part A.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement** the CLI; then write `SKILL.md`: frontmatter
  per AGENTS.md (`name: docshelf-build`, a "Use when" description such as
  "Use when documentation you need offline is not on DevDocs or in
  Dash/Zeal but its site publishes a Sphinx objects.inv (Sphinx,
  PyDoctor, MkDocs with mkdocstrings), to build a trimmed docshelf docvol
  from it", `compatibility: Network access to fetch from a docs site;
  pairs with the docshelf skill.`, `version: "0.1.0"`); body: the
  plan-review-build loop, reading the summary, choosing `--full` for
  prose reference, guides stay on the web, rebuild, where files live.
- [ ] **Step 4: Run the whole suite, expect PASS**: `python3 -m unittest discover -s tests -v`;
  `python3 scripts/ci_changed_skills.py --base main --check-versions`;
  `npx skills add . --list` shows `docshelf-build`.
- [ ] **Step 5: Real-data check (network, not in tests):** build Yosys
  from `https://yosyshq.readthedocs.io/projects/yosys/en/stable/` with
  defaults; expect about 49 full and 65 stub pages; spot-check `search`
  and `show` on a `cmd:` entry through docshelf. Record numbers in the PR.
- [ ] **Step 6: Commit and push** `docshelf-build: CLI and SKILL.md`;
  update PR #29's body (version, testing, checklist).

### Task 8: Agent trial

- [ ] Per AGENTS.md "Testing skills with small models": one task ("build
  offline docs for Yosys and look up the `opt` pass's options") with and
  without the skill, in the `sandboxing` skill's sandbox; grade from tool
  calls in the JSON events. Record results in the PR's Testing section.
