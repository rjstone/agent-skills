---
name: docshelf-build
description: Use when documentation you need offline is not on DevDocs or in Dash/Zeal and you have its web site or a local copy of its build - a Sphinx objects.inv (Sphinx, Read the Docs, PyDoctor, MkDocs with mkdocstrings) or an llms.txt page list (Mintlify, Starlight and others) - to build a trimmed docshelf docvol from it.
compatibility: Network access to fetch from a docs site; pairs with the docshelf skill.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.4.0"
---

# docshelf-build

Build a docshelf docvol from a documentation web site, or a local copy of
its build, with a method chosen by the site type. Run
`python scripts/docshelf_build.py` (stdlib only; the path is relative to
this skill's folder; `--help` lists the commands). The result is listed by
docshelf as `built` and looked up with docshelf as usual; that needs
docshelf 0.9.0 or later (`docshelf.py --help` prints the version).

Check docshelf first: `docshelf.py sources NAME` finds DevDocs and Dash/Zeal
documentation, which is better than a build when it exists. This skill
refuses a name DevDocs already has.

## 1. Find the site type

`python scripts/docshelf_build.py detect URL_OR_PATH` looks for the files a
build reads and prints the type, the SOURCE to plan and the file to read
next:

```
type: sphinx
source: https://docs.example.org/en/latest/
read: BUILD-sphinx.md
also: llms (https://docs.example.org/llms.txt)
```

Give it the docs' base URL (or a page in it) or a local folder. When a site
has both, Sphinx wins: its inventory types every API entry and separates
reference from guides. To build from the other one anyway, pass its index
as SOURCE. Exit 3: neither was found; exit 4: the site could not be reached.

## 2. Read the file for that type

- **sphinx** (`objects.inv`: Sphinx, Read the Docs, PyDoctor, MkDocs with
  mkdocstrings): [BUILD-sphinx.md](BUILD-sphinx.md). Reference pages in
  full, guides as stubs that link to the live page.
- **llms** (`llms.txt`: Mintlify, Starlight and others):
  [BUILD-llmstxt.md](BUILD-llmstxt.md). Every listed page in full, cached,
  narrowed by sub-index and sorted into reference and guides with
  `classify`.

Read only the one you need. Both use the same commands: `plan SOURCE --name
NAME`, check the summary, `build NAME`.

## Files and commands for every type

Under docshelf's cache (`DOCSHELF_CACHE_DIR`, else `~/.cache/docshelf`, on
Windows `%LOCALAPPDATA%\docshelf\cache`): the docvol in `built/NAME/`, the
plan in `built-plans/NAME.json`. The docvol's `meta.json` carries
`"format": 1`, the version of this layout that docshelf checks. In the
plan, setting a page's `"keep"` and `"why": "manual"` pins it across
re-plans. `list` shows built and planned docvols; `remove NAME` deletes a
docvol and keeps its plan (`--plan` too).

Exit codes: 2 usage or name, 3 no usable index (no Sphinx inventory, no
llms.txt), 4 network.

Guides and tutorials stay on the web on purpose: they are slow, wordy
reading for an agent. Condensed agent guidance belongs in a skill.
