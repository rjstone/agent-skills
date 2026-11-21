---
name: docshelf-build
description: Use when documentation you need offline is not on DevDocs or in Dash/Zeal but its site publishes a Sphinx objects.inv (Sphinx, PyDoctor, MkDocs with mkdocstrings) or an llms.txt page list (Mintlify, Starlight and others), to build a trimmed docshelf docvol from it.
compatibility: Network access to fetch from a docs site; pairs with the docshelf skill.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.2.0"
---

# docshelf-build

Builds a docshelf docvol from a Sphinx-style docs site with
`python scripts/docshelf_build.py` (stdlib only; the path is relative to this
skill's folder). The result is listed by docshelf as `built` and looked up
with docshelf as usual; that needs docshelf 0.9.0 or later (`docshelf.py
--help` prints the version): older ones never show built docvols. Run
`--help` for the commands.

Check docshelf first: `docshelf.py sources NAME` finds DevDocs and Dash/Zeal
documentation, which is better than a build when it exists. This skill
refuses a name DevDocs already has.

## Is the site Sphinx?

It is when `<site base URL>objects.inv` downloads (a binary file starting
`# Sphinx inventory version 2`). Read the Docs sites
(`*.readthedocs.io/en/<version>/`), most Python projects' docs, and MkDocs
sites with mkdocstrings have one. Use the folder that holds `objects.inv`
as SOURCE, a site URL or a local HTML build (`_build/html`).

## The loop

1. `plan SOURCE --name NAME` reads the inventory, writes the plan and prints
   a summary: pages kept in full, pages made stubs, and the largest page
   groups. Nothing else is downloaded.
2. Check the groups. The rule keeps in full every page with API entries
   (Python functions, classes, a project's own command or option roles) and
   makes the rest stubs (title, section, link to the live page). If a
   group of prose pages is really reference (a language manual, an options
   page), rerun with `--full 'group/*'`; drop noise with `--stub PAT`.
   Patterns are shell globs on page paths, later ones win, and they are
   kept in the plan (`--reset` clears them, `--all` keeps everything).
3. `build NAME` fetches only the full pages (politely: one request at a
   time, robots.txt honoured) and writes the docvol. A page that fails
   becomes a stub with the error; the build still finishes.
4. Look things up with docshelf: `search WORDS -d NAME`, `show NAME:PAGE`.

`build SOURCE --name NAME [plan options]` does 1 and 3 in one step. Plan
options (`--full`, `--stub`, `--all`, `--reset`, `--base-url`) go with
`plan` or with a SOURCE, never with `build NAME`: to change a built
docvol, run `plan SOURCE --name NAME ...` again, then `build NAME`. A
rebuild (`build NAME`) reuses the plan; if the inventory changed, new pages
get the rule and overrides and gone pages are dropped.

A warning that no page has a domain role means the site is all prose: keep
the groups you need with `--full`, or the docvol is stubs only.

## llms.txt sites

For a site that publishes `llms.txt` (a Markdown list of page links; Mintlify,
Starlight and others), SOURCE is the `llms.txt` URL (a sub-index URL, or a
local `.txt` file, also works). Every listed page is kept in full; nothing
becomes a stub unless you ask (`--stub PAT`). Sub-indexes on the same host
are followed three levels deep.

- `plan` prints the index tree and page counts. For a large site (over 300
  full pages warns) narrow before building: plan a sub-index as SOURCE
  with its own `--name`, or add `--stub 'group/*'`. `--base-url` is for
  Sphinx only.
- `build` downloads pages into a page cache (`built-src/NAME` in the docshelf
  cache) and reuses it; `build NAME --refetch` downloads them again. A page
  that fails keeps its cached copy and records `fetch_error` in the plan.
  `remove NAME` deletes the cache too.
- If the index changed, `build` re-plans and prints what was added and dropped.
- Each page's plan entry holds `signals` (counts such as code and signature
  lines) for a later reference-vs-tutorial classifier; a choice written as
  `"why": "model:<id>"` (with its `keep` and `description`) survives
  re-planning.

## Files

Under docshelf's cache (`DOCSHELF_CACHE_DIR`, else `~/.cache/docshelf`, on
Windows `%LOCALAPPDATA%\docshelf\cache`): the docvol in `built/NAME/`, the
plan in `built-plans/NAME.json`. The docvol's `meta.json` carries
`"format": 1`, the version of this layout that docshelf checks. In the
plan, setting a page's `"keep"` and `"why": "manual"` pins it across
re-plans. `list` shows built and planned
docvols; `remove NAME` deletes a docvol and keeps its plan (`--plan` too).

Exit codes: 2 usage or name, 3 not a Sphinx inventory, 4 network.

Guides and tutorials stay on the web on purpose: they are slow, wordy
reading for an agent. Condensed agent guidance belongs in a skill.
