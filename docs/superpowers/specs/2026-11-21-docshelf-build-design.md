# docshelf-build: Sphinx sites to agent-sized docvols

Date: 2026-11-21. Status: draft for review.

## Intent

docshelf reads DevDocs documentation and Dash/Zeal docsets offline. Much
documentation is in neither catalog (e.g. Yosys, SpinalHDL). The goal is to
turn such documentation into a docshelf docvol, downloaded whole up front
like a DevDocs install, so agents can look things up offline and fast.

The main users are agents. People read tutorials slowly enough that the
website is fine for them; agents read fast and mostly need dense reference.
Agent "tutorials" are skills (condensed, tested by trial and fix), not
docshelf's job. So a built docvol keeps **reference pages in full** and
reduces **guide/tutorial pages to stubs**: title, section, a one-line
description where available, and the live URL (the user, 2026-11-21).

This design covers the first source format, **Sphinx** (anything that
publishes an Intersphinx `objects.inv`: Sphinx, PyDoctor, MkDocs with
mkdocstrings). Other formats are later projects (TODO.md, docshelf 8.x):
llms.txt sites, generic HTML, PDF.

## Goals

- A new skill `docshelf-build` (the user, 2026-11-21: separate, so
  agents that only look things up can ignore it) that builds a docvol from
  a Sphinx site URL, or a local Sphinx HTML build folder.
- Decide full vs stub per page with a free, offline rule (approach A),
  written to an editable **plan file**, so a later decision-model step
  (approach B) can write the same file without changing the build.
- docshelf (`search`, `show`, `toc`, `types`, `fts`, notes) works on a
  built docvol with no change to how it reads docvols.
- Standard library only.

## Non-goals

- Writing Dash docsets.
- llms.txt, generic HTML, PDF, crawling sites without an index (later).
- A decision model (approach B) in this version; only room for it.
- Condensing guides into agent-optimized text (that is skill writing).
- Fetching pages on demand at lookup time.

## Anti-goals (failure even if it "works")

- A built docvol that docshelf's `install` or `update` can silently
  overwrite with a DevDocs one of the same name.
- Bundles bloated with tutorial prose: the point is small and dense.
- Hammering a docs site (unbounded parallel fetches, ignoring robots.txt).
- Non-stdlib dependencies, or anything that breaks the public-repo rules.

## Constraints

- Two skills may be installed in different places, so `docshelf-build`
  cannot import docshelf's scripts. **The on-disk docvol format is the
  contract** between them; the build writes it standalone.
- docshelf's DevDocs docvol folder: `<cache>/devdocs/<name>/` holding
  `index.json` (`{"entries": [{"name", "path", "type"}], "types":
  [{"name", "count", "slug"}]}`), `db.json` (`{page: html}`), `meta.json`
  (`name`, `release`, `version`, `mtime`, `installedAt`, `alias`,
  `entry_count`). The folder name is the docvol name (`family~version`).
  `<cache>` is `DOCSHELF_CACHE_DIR` or docshelf's default.
- Read the Docs returns HTTP 403 to Python's default User-Agent
  (`Python-urllib/3.x`) and accepts a custom one (checked 2026-11-21).
- Tests: stdlib `unittest`, no network (fixtures).
- New skill process: branch `skill/docshelf-build`, squash-merge.
  docshelf's change: branch `update/docshelf`, version bump, merge commit.

## Evidence (2026-11-21)

Yosys's `objects.inv`: 1,924 entries over 114 pages. Roles: `std:label`
876, `cmd:cmdusage` 383, `cmd:cmd` 301, `cell:cell` 254, `std:doc` 107,
`cell:prop` 3. The 49 pages with non-`std` roles are the command and cell
reference (`cmd/`, `cell/`); the 65 with only `std:*` roles are guides
(`using_yosys/`, `getting_started/`, `yosys_internals/`, `appendix/`).
SpinalHDL also publishes `objects.inv`; most of its reference is probably
prose pages with only `std:*` roles, which the rule alone would stub
(hence the overrides).

## Approaches considered

- **A. Role rule + editable plan (chosen, the user, 2026-11-21).** A page
  with any non-`std:` role is `full`; others are `stub`. Path-pattern
  overrides and a hand-editable plan file. Deterministic, offline, free.
- **B. A + decision model** classifying `std`-only pages and writing stub
  descriptions. Better on prose-reference sites; needs a key, network,
  varies between runs. Deferred; the plan file is its interface.
- **C. Fetch everything, rank reference higher at search time.** Rejected:
  loses the small bundle.

## Design

### Commands

`python scripts/docshelf_build.py <command>`:

- `plan SOURCE [--name NAME] [--full PAT]... [--stub PAT]... [--all]`
  Reads `SOURCE/objects.inv` (a site base URL or a local folder), applies
  the rule and overrides, writes the plan file, prints a summary (pages
  full/stub, entries, estimated download). Fetches nothing else.
- `build NAME` - fetches the `full` pages listed in the plan, writes the
  docvol. Re-running rebuilds (replaces atomically).
- `build SOURCE [plan options]` - `plan` then `build` in one step.
- `list` - built docvols with source URL and build date.
- `remove NAME` (or leave removal to docshelf; builder's call).

`--full`/`--stub` patterns are shell globs on page paths
(`'yosys_internals/*'`); later ones win; `--all` makes every page full.

### Plan file

`<cache>/built-plans/<name>.json`, outside the docvol folder, so a plan
can exist before the first build, docshelf never sees a half-made folder,
and a rebuild's atomic replace of the docvol leaves the plan alone
(decision after review, 2026-11-21). A rebuild or update reuses it:

```json
{
  "format": 1,
  "source": "https://yosyshq.readthedocs.io/projects/yosys/en/stable/",
  "inventory_sha256": "...",
  "project": "YosysHQ Yosys", "version": "",
  "rule": "roles",
  "overrides": [["full", "yosys_internals/*"]],
  "pages": {
    "cmd/index_passes_opt.html": {"keep": "full", "title": "...", "why": "roles: cmd:cmd"},
    "getting_started/installation.html": {"keep": "stub", "title": "Installation",
      "section": "Getting started", "description": null, "why": "roles: std only"}
  }
}
```

`why` records what decided (`roles: ...`, `override: <pattern>`,
`manual`, later `model: <id>`). `description` is null under approach A;
approach B fills it. A hand edit of `keep` is respected on rebuild (mark
it `"why": "manual"`).

Re-running `plan` on an existing plan (decisions after review,
2026-11-21):

- New `--full`/`--stub` flags are **appended** to the stored `overrides`
  (later wins); `--reset` clears the stored overrides first; `--all` is
  stored as the override `["full", "*"]`.
- Precedence per page: `manual` > overrides (last match wins) > the role
  rule. Later `model:` decisions rank with the role rule (below
  overrides and manual).
- When the inventory changed: new pages get rule + overrides; pages no
  longer in the inventory are dropped, manual marks included; the
  summary lists added and dropped pages.

Page keys: the inventory URI's path without the anchor, a trailing
`.html`, or a trailing `/` (`cmd/opt.html` -> `cmd/opt`, MkDocs/dirhtml
`api/foo/` -> `api/foo`; the root becomes `index`). Fetching uses the URI
exactly as the inventory gives it (from a local folder, `x/` reads
`x/index.html`). Both `.html` and directory-style sites are in scope for
0.1.0 (decision after review, 2026-11-21).

Local folder sources: `--base-url URL` gives stubs a live link; without
it a stub says the page was left out of the build and names its path in
the source folder.

### Built docvol

Location: `<cache>/built/<name>/` with the same three files as a DevDocs
docvol. `meta.json` adds `"origin": "docshelf-build"`,
`"source"` (URL or folder) and `"inventory_sha256"`. Name: from `--name`,
else derived from the inventory's project and version
(`yosys`, `spinalhdl~master`), checked against docshelf's slug rule.

- `index.json` entries: every inventory entry on a `full` page, with
  `path` = page path without `.html` plus `#anchor`; one entry per `stub`
  page (`std:doc`) so search still finds it. Entry `type`: the role's
  readable label (`cmd`, `cell`, `function`, ...), and `Guide` for stubs.
  Mapping roles onto Dash's entry types is TODO 8.7, not this version.
- `db.json`: `full` pages as cleaned HTML (only the main content block,
  e.g. Sphinx's `div[role=main]`/`article`/`div.body`; no navigation,
  sidebars, scripts or styles; internal links rewritten to page paths so
  docshelf's link resolution works). `stub` pages as a few lines of HTML:
  title, section, description if any, and "Not stored; read it at <URL>".
- Links from a full page to a stub page still resolve (to the stub).

### Fetching

- One worker by default, small optional parallelism (max 4), a short delay
  between requests, honour `robots.txt` (`urllib.robotparser`), and a
  `User-Agent` of `docshelf-build/<version>`.
- Retries with backoff on 429/5xx; a page that still fails is stored as a
  stub with the error noted, and the build reports it (not fatal).
- Write to temp files and replace at the end, so a failed build leaves the
  previous docvol intact (as docshelf's `install` does).

### Change to docshelf (`update/docshelf`)

- Discover `<cache>/built/*` too, as `source = "built"` docvols (same
  reader as DevDocs). Its "repair" hint names `docshelf-build build NAME`,
  not `install`.
- Names (decisions after review, 2026-11-21): `docshelf-build` refuses a
  name that is in docshelf's cached DevDocs list or already installed
  from DevDocs, and says to `docshelf install` it instead (if DevDocs has
  it, building is unnecessary). docshelf's `install` refuses a name that
  is already built. So the two never share a name; if a clash is found
  anyway (e.g. hand-made folders), the built one wins and a warning says
  so, because the user made it on purpose.
- `update` with no names skips built docvols silently; `update NAME` on a
  built one refuses and points to `docshelf-build`.
- `list` shows them as built; `remove` works on them (or refuses and points
  to `docshelf-build remove`; builder's call, but consistent).
- SKILL.md: one line saying built docvols come from `docshelf-build`.

### Skill text

`skills/docshelf-build/SKILL.md`: when to use (documentation not on
DevDocs or Dash/Zeal, site has `objects.inv`), the plan-review-build loop,
how to choose overrides (look at the plan summary's page groups; keep
prose reference full), and that guides stay on the web. Frontmatter per
AGENTS.md, version `"0.1.0"`, `compatibility` noting network access for
`plan`/`build` from a URL.

### Tests

Fixtures: a small `objects.inv` (written by the test with zlib) and a few
Sphinx-like HTML pages in a temp folder (the local-folder source covers
the build path without network). Cover: inventory parsing (incl. `$`
shorthand in URIs and `-` display names), the role rule, overrides order,
plan round trip with manual edits, content extraction and link rewriting,
stub pages, atomic replace on failure, and docshelf reading the result
(a test in docshelf's suite that loads a built fixture folder).

## Left to the builder

- Exact HTML cleaning rules and the content-block selectors' order.
- Readable labels for roles and the entry-type names.
- Concurrency default, delay, retry counts.
- Whether `remove` lives in docshelf, docshelf-build, or both.
- Script file layout inside the skill.

## Later (not this version)

- Approach B: a `--describe`/`--classify` step using a decision model
  that rewrites `keep`, `description` and `why` in the plan.
- An `update` that re-fetches only when `inventory_sha256` changes.
- llms.txt sites (TODO 8.9), generic HTML (8.2), PDF.
