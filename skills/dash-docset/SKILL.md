---
name: dash-docset
description: Use when you need exact API, framework or library reference from Dash docsets (Kapeli, user-contributed, cheat sheets) offline, or when installing, updating, searching or annotating docsets from the command line.
compatibility: network access needed for docset downloads and source lists; searching installed docsets works offline. Host allowlist in assets/allowlist.txt.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Dash docsets

Install Dash docsets and search them offline with `python scripts/docset.py`
(stdlib only). The script's `--help` and `<command> --help` are the command
reference; this file covers only what they don't.

## When to use

Use for exact, version-pinned reference (signatures, options, return values)
that should be quoted from the docs, offline or without a network round trip.
Prefer Context7 or web search when the library has no docset or you need the
very latest release; prefer a per-library skill when one exists and covers the
task. Docsets can be stale: check `list` for versions. See "Other options"
below before installing, in case another tool suits the user better.

If the network only reaches allowed hosts (a sandbox, a corporate proxy, a
cloud agent environment) and downloads or source lists fail, give the user
[assets/allowlist.txt](assets/allowlist.txt): the hosts to allow.

Kapeli's terms (README of github.com/Kapeli/feeds) allow its docsets for
personal use or with Dash or Zeal, and not in other applications without
Kapeli's permission. If the use looks non-personal (a product, a service,
a shared team tool), point the user to those terms. User-contributed
docsets carry their own licences.

## First run: pick a setup

Run `python scripts/docset.py where`. If it prints a location, skip to the
workflow. Otherwise run `where --discover`: it lists installed Dash or Zeal
apps and existing docset folders. Then decide where you are running:

1. **The user's own computer (a desktop):**
   - A. Dash or Zeal installed: use their docsets. Add the folder with
     `where --set STORE --user --read-from DIR`. STORE still holds notes and
     search indexes; suggest `~/.local/share/dash-docset`. When a needed
     docset is missing, ask the user to download it in the app (Dash:
     Settings > Downloads; Zeal: Tools > Docsets), not with this script.
     With Dash, also suggest Kapeli's Dash MCP server (see "Other options").
     `--discover` checks Zeal's default folder on Linux, macOS and Windows
     (also Flatpak and portable installs) and a folder set in Zeal's
     settings, and Dash's default `~/Library/Application Support/Dash/DocSets`.
     If the app has docsets that `--discover` doesn't list, ask the user
     where they are (Dash: Settings > Docsets; Zeal: Edit > Preferences >
     Docsets) and pass that folder to `--read-from`.
   - B. Neither installed: suggest installing Zeal (Linux, Windows) or
     Dash (macOS), downloading the docsets there, then continuing as in A.
   - C. The user declines: the script downloads docsets itself. Offer a
     permanent central folder (suggest `~/.local/share/dash-docset`) or
     `.docsets/` in their project (the script writes a `.gitignore` that
     keeps only `notes/`; warn that docsets are large).
2. **A cloud sandbox, CI or other throwaway machine** (no desktop apps, a
   fresh home folder each session):
   - A. If some folder survives between sessions (a mounted volume, a
     cache the platform keeps), ask the user and use it as the store.
   - B. If nothing persists, use a temporary folder and install only the
     docsets the current task needs, one at a time, when needed. Prefer a
     cheat sheet when it answers the question; skip `update`.

Never pick a location yourself: the user chooses or approves it. If unsure
which case applies, ask. If a folder meant to be permanent is under a
temporary location (`/tmp`, `%TEMP%`), say it may be cleared. Run `where --set PATH (--project|--user)
[--read-from DIR]` with the choice (`--project` writes `.dash-docset.json`
in the current folder; `--user` writes `~/.config/dash-docset/config.json`,
or `%APPDATA%\dash-docset\config.json` on Windows); quote a `~` path
(`'~/.local/share/dash-docset'`) so the config keeps the portable form.

Never write into a Dash, Zeal or dasht folder; docsets found there are
read-only to the script (`update` and `remove` refuse them). `install` skips
a docset that is already installed at that version, or already available
from one of those folders (`--force` overrides).

## Workflow

1. Find a docset: `sources QUERY` (matches names, titles and keywords),
   then `install NAME` (several at once is fine). Prefix names when you
   can (`kapeli:Name`, `user:Name`, `cheat:Name`); a prefix is required
   when sources share a name. Official names match Dash's feed files
   (`kapeli:Python`, `kapeli:NodeJS`, `kapeli:Django`) or Zeal's names
   (`kapeli:Python_3`, `kapeli:Python_2`). `kapeli:Python` is the newest
   Python; `kapeli:Python_3` is the same feed limited to 3.x (and
   `Python_2` to 2.x), so `update` never crosses that line. Git is only a cheat sheet
   (`cheat:Git`). Pin an older official version with `@`:
   `kapeli:Python@3.12` installs the newest 3.12.x and `update` keeps the
   pin. A not-found error suggests close names and the other prefixes.
   Source lists are cached for a week; `sources --refresh` re-checks them.
   A "note (no action needed)" on stderr says a list came from a fallback
   source because another was unreachable; results are complete. Cheat
   sheets are short (Git's has 81 entries); prefer a full docset when one
   exists.
2. `search QUERY` finds entries by name and prints a REF for each. Several
   words need no quotes; a name must contain all of them (`search walking
   speed` finds `hero:get_walking_speed()`). Hits
   below the "fuzzy matches" line only share letters in order; treat them
   as misses. No hits prints "no matches" and exits 0 (exit 5 means a
   named docset or REF doesn't exist).
3. `show REF` prints that entry's trimmed section plus your notes. The
   default cap is 150 lines; `--full` lifts it (page REFs from `fts` are
   capped the same way). Respect `--max-lines` on
   `search`, `fts` and `show` instead of dumping everything.
4. `fts QUERY` searches the text inside pages when entry names don't match.
   Function options, parameters and settings are often only in page text
   (e.g. `read_csv`'s `skip` is a row in a table), so look for them with
   `fts`.
   Each hit prints `<Name>:page:<path>#<anchor>`: `show` on it prints the
   section around the match (without `#<anchor>`, the whole page). The
   first `fts` on a docset builds its index (seconds for large docsets);
   `index-text NAME` builds it ahead of time.
5. Manage: `list` shows installed docsets and versions, `update [NAME]`
   refreshes one or all, `remove NAME` deletes one (notes are kept).
6. Exit codes are listed at the end of `--help` (3: location not set,
   5: not found, 7: network or incomplete source list).
7. Scope: a project `"docsets"` list in `.dash-docset.json` limits searches to
   those docsets. Without one, searches cover every docset unless more than 4
   are full-size; then narrow with `-d NAME` (repeatable), set the list, or
   pass `--all`.

## Notes

Keep durable lessons (gotchas, project conventions) in the docset's notes
file. Find it with `notes DOCSET --path` (creates the `notes/` folder; the
file itself appears when you write it),
and edit it with normal file tools. Format: a `## General` section, plus
`## <entry name>` sections: the name as `search` prints it, or its part
before `(` (`## sol.timer.start` covers `sol.timer.start([context], ...)`),
with an optional ` (Type)` suffix to disambiguate. Only
`show` prints notes: General and the matching section (General alone for
page REFs), so many small sections are cheap and one big one is not.

Run `notes DOCSET --check` after editing: it warns about oversized notes and
headings that match no entry. On a size warning, suggest to the user turning
the heavy section into its own minimal skill built around the tasks it
covers.

## Other options

Mention these to the user when they fit better:

- Dash installed (macOS): Kapeli's MCP servers talk to the Dash app and use
  its docsets and search directly: https://github.com/Kapeli/dash-mcp-server (Python)
  or https://github.com/Kapeli/dash-mcp-server-node (Node.js).
- An MCP server instead of a CLI, without Dash or Zeal:
  https://github.com/keturn/ZDocsetMCP.
- Reading docs directly in a viewer app: Zeal (Linux, Windows;
  https://zealdocs.org/) or Dash (macOS; https://kapeli.com/).
- Docset sources, to browse or contribute:
  https://github.com/Kapeli/Dash-User-Contributions and
  https://github.com/Kapeli/cheatsheets.
