# dash-docset: changes after the plan

Companion to the plan (`2026-11-14-dash-docset.md`, executed through commit
`2e4fc87`, "final review fixes") and the design
(`../specs/2026-11-14-dash-docset-design.md`). Those two record what was
planned. This file records the calls made while executing it and every change
made afterwards, and says which statements in them no longer hold. Where they
disagree, this file and the code win.

Status (2026-11-14): draft PR #6, branch `skill/dash-docset`. Not to be merged
until Kapeli replies about the docset terms (see "Open").

## Rulings made while executing the plan

Calls the plan left to the builder, reported to the user at the end of the
plan:

1. **Unmanaged docsets:** a docset in the store that `installed.json` doesn't
   record is sized like a foreign one (full size only at 500+ entries).
   `update` and `remove` refuse it.
2. **Page REFs:** `Name:page:<path>` has its own parser; the entry REF parser
   is unchanged.
3. **Full-text index staleness:** an index is rebuilt when the docset's
   version changes. Foreign docsets have no version, so their index is
   rebuilt when the docset's own `docSet.dsidx` modification time changes.
4. **Exit 7** is for network and archive errors.
5. **`--dir` and `DASH_DOCSET_DIR`** still read the configured `read_from`
   folders. A broken config file doesn't block `--dir`. Tests ignore the
   user's real environment variables.
6. **`installed.json`** is `{name: {source, version, url, installed}}`.
   `pin` was added later, for version pins.
7. **`show --full`** keeps the section trim and lifts only the line cap. The
   whole page is a page REF.
8. **Prefixed installs** (`kapeli:`, `cheat:`, `user:`) build the download
   URL directly instead of listing the whole source, so they work while the
   GitHub API is rate-limited or blocked. A 404 is "not found" (exit 5).
9. **Notes names:** names containing `..` are refused, which closes a path
   escape.

## Changes after the plan, in order

| Commit | Change | Why |
|---|---|---|
| `5ea7afd` | `VERSION` constant used in `--version`, `--help` and the User-Agent. It may lag `metadata.version` but never lead it (a test checks). | the user |
| `5adc973` | Fixes from agent trial 1: not-found errors suggest close names and the other prefixes; `sources` says when its list is incomplete (exit 7); `fts` prints "no matches" and announces its first index build; `notes --path` creates `notes/`, `notes --check` prints "ok", notes keep their headings; `where` exits 3 when unset. | trial 1 |
| `aa53528` | Fixes from agent trial 2: fts REFs became page REFs with the anchor nearest the match; `show` accepts `Name:page:<path>#<anchor>`; page text drops navigation chrome; `search` marks fuzzy matches; `--help` lists exit codes. | trial 2 |
| `dc640e3` | More source lists, version pins and a polite Zeal fallback (see "Sources"). `sources` matches titles and keywords. | the user, after reading zealdocs/backend |
| `24fc46b` | Fixes from agent trial 3: fts matches are located with control-character snippet marks, because docs contain literal brackets; `search` and `fts` stop printing notes; `fts --max-lines` cuts whole hits; a stderr note when a list came from a fallback; Kapeli's terms and viewer apps in `SKILL.md`. | trial 3 |
| `0533a99` | Bundled starter lists in `assets/` put on hold. | the user (waiting for Kapeli) |
| `6d294e8` | `assets/allowlist.txt` lists every host the script contacts, and `compatibility` points to it. A test fails if the script uses a host that isn't listed. | the user |
| `9e6abd6` | Setup order: Dash/Zeal first, then script downloads (see "Setup"). `where --discover` lists installed apps. `install` skips a docset already installed at that version or available from Dash/Zeal/dasht, unless `--force`. | the user |
| `0b7c3e6` | Zeal and Dash docset folders on Linux, macOS and Windows (see "Facts"). | the user |
| `ebfa8bd` | Pages are read from tarix docsets (Dash's compact storage). GNU Texinfo `¶` links are stripped. | the user |
| `32b9fad` | Fixes from the Solarus trials: notes headings also match an entry name without its argument list (`## sol.timer.start`), and an unmatched heading gets a hint and a "did you mean"; at most 5 fuzzy hits when real hits exist; fallback notes print only when their source is in the results, worded "no action needed". | Solarus trials |
| `bcc0085` | `search`, `fts` and `sources` take several words without quotes; a search name must contain all of them, in any order. "No matches" points to `fts`. | Solarus rerun |
| `3301f12` | `search` treats `f(a, b)` as an exact match for `f` and lists anchored entries before whole-page entries; `show` starts an entry without an anchor at a heading named like it. Some docsets (DuckDB) have both kinds for one function. | DuckDB trial prep |
| `4fb4c1e` | `SKILL.md`: the user config path, a warning when a "permanent" folder is temporary, and that options and settings are found with `fts`. | DuckDB trial |
| `dff734b` | `fts` prints the short entry REF when the matched section is an entry's, trying every id on the block (DuckDB headings carry a Dash `//apple_ref` id plus the entry's id). | DuckDB trial |
| `b30f065` | Fixes from the Morello trials: `install` says the name to use when it differs from the source name (`user:Arm Morello A64 ISA` → `arm64morello`); fuzzy search hits are hidden when real hits exist; table cells spanning several columns are labelled (`Rm (5 cols)`), so encoding diagrams can be read as text; `SKILL.md`: the script path is relative to the skill folder, and note headings for variants. Navigation footers are left alone: nothing identifies them reliably, and stripping must never remove real docs (the user, 2026-11-14). | Morello trials |

## What the plan and design say that no longer holds

| Plan or design says | Now |
|---|---|
| Design, "Storage location": four choices offered to the user. | `SKILL.md` follows the setup order below. The four choices remain as option 1C. |
| Design "Notes" and plan Task 6: `search` prints General notes. | Only `show` prints notes: General plus the matching section; General alone for page REFs. |
| Plan Task 7: an fts `ref` is the first entry pointing into the page. | An fts `ref` is `Name:page:<path>#<anchor>`, anchored at the id nearest before the match. The match is found from the FTS snippet: two words before it plus up to three from it, stopping at sentence ends. Snippets mark matches with `\x02`/`\x03` internally and print `[ ]`. |
| Plan Task 8: cheat sheets have no index, so names come from the GitHub repo and the version from `Last-Modified`. | Kapeli's index `https://kapeli.com/feeds/zzz/cheatsheets/cheat.json` exists. It gives versions and aliases, and has trailing commas that must be stripped. `Last-Modified` is only a fallback. |
| Plan Task 8: the official list comes from the GitHub API only. | The GitHub API plus Zeal's manifest, with Zeal's catalog as a last resort (see "Sources"). |
| Plan Global Constraints: `compatibility` "network access to Kapeli feeds and GitHub ...". | "network access needed for docset downloads and source lists; searching installed docsets works offline. Host allowlist in assets/allowlist.txt." |
| Design "Non-goals": MCP mode in TODO. | Still in TODO, now with "look at ZDocsetMCP first". `SKILL.md` also points to Kapeli's Dash MCP servers and ZDocsetMCP as alternatives. |
| Plan: pages live in `Contents/Resources/Documents/`. | Pages come from `Documents/`, or else from `tarix.tgz` through `tarixIndex.db`. |

## Setup (the user, 2026-11-14)

1. **On the user's own computer**
   - **A. Dash or Zeal installed:** read their docsets in place, read-only
     (`--read-from`). The user downloads missing docsets in the app. With
     Dash, the agent also suggests Kapeli's Dash MCP server.
   - **B. Neither installed:** suggest Zeal (Linux, Windows) or Dash (macOS),
     then continue as in A.
   - **C. The user declines:** the script downloads to a central folder or to
     `.docsets/` in the project.
2. **On a cloud sandbox, CI or other throwaway machine**
   - **A.** Use a store that persists between sessions.
   - **B.** Otherwise use a temporary store with on-demand installs only.

## Sources (order, the user, 2026-11-14)

| List | Tried in order |
|---|---|
| Official | GitHub API listing of Kapeli/feeds, plus Zeal's manifest (`zealdocs/backend` `docsets.json` on raw GitHub); then Zeal's catalog |
| Cheat sheets | Kapeli's `cheat.json`; then the GitHub API listing of Kapeli/cheatsheets; then Zeal's catalog |
| User-contributed | Kapeli's `index.json`; then Zeal's catalog |

How the lists are fetched (`cached_get`):
- **Caching:** each list is kept with its ETag/Last-Modified and re-checked
  at most weekly with a conditional request. After a failure it isn't
  retried for a day.
- **Zeal's catalog** (`https://api.zealdocs.org/_api/v1/catalog.json`, a
  best-effort public service with no stability promise) is never forced to
  refresh, even by `sources --refresh`. It's stored without icons, about
  3.8 MB less.
- **Name lookup:** `kapeli:Python_3` uses the Zeal manifest's `source` and
  `versionPrefix`.
- **Pins:** `kapeli:Python@3.12` picks the newest matching version from the
  feed's `other-versions` and downloads it from
  `https://<mirror>/feeds/zzz/versions/<Feed>/<version>/<Feed>.tgz` (the
  pattern from zealdocs/backend `src/mirror-url.ts`). `update` keeps the
  pin.

## Facts checked (2026-11-14)

- **Feed names have no version suffix:** `Python.xml` exists, `Python_3.xml`
  doesn't. Git has only a cheat sheet.
- **Python 3.15.0 is a release, not a pre-release.** Trial 2 called it a
  pre-release, which was wrong.
- **Download hosts:** a sample of 17 official feeds all list the same five
  mirrors (sanfrancisco, london, newyork, tokyo, frankfurt `.kapeli.com`).
- **The mirrors use no CDN:** single A records, no CNAME, Linode addresses.
  `sanfrancisco.kapeli.com` resolves to the same address as `kapeli.com`.
- **Zeal's docset folder:** the `docsets/path` setting, else Qt's
  AppLocalDataLocation (organization "Zeal", app "Zeal") plus `/docsets`
  (from zealdocs/zeal `settings.cpp` and `main.cpp`):
  - Linux: `$XDG_DATA_HOME/Zeal/Zeal/docsets`
  - macOS: `~/Library/Application Support/Zeal/Zeal/docsets`
  - Windows: `%LOCALAPPDATA%\Zeal\Zeal\docsets`
  - Flatpak: under `~/.var/app/org.zealdocs.Zeal/data/`
  - Portable builds: `docsets` and `zeal.ini` beside `zeal.exe`
- **Zeal's settings:**
  - Linux: `~/.config/Zeal/Zeal.conf`, `[docsets] path=`
  - macOS: `~/Library/Preferences/org.zealdocs.Zeal.plist`, key
    `docsets.path`. The key name is inferred from Qt's rules, not seen in a
    real file.
  - Windows: registry `HKCU\Software\Zeal\Zeal\docsets`, value `path`.
- **Dash** (macOS only): `~/Library/Application Support/Dash/DocSets/<Name>/<Name>.docset`.
  Kapeli's guide doesn't document other locations.
- **Tarix** (from Zeal's `tarixarchive.cpp`, checked on Kapeli's Bash
  archive):
  - `tarix.tgz` is an ordinary `.tgz` with a zlib full flush before every
    tar record.
  - `tarixIndex.db` has the table
    `tarindex(path TEXT PRIMARY KEY COLLATE NOCASE, hash TEXT)` and a
    `toextract` table. Paths start with `<Name>.docset/`, and `hash` is
    `"<block> <offset> <blocks>"`.
  - Kapeli serves the index as `<archive>.tgz.tarix`, a `.tgz` holding the
    SQLite file.
  - Zeal is GPL-3, so it was read for the format only; our code is our own.
- **Kapeli's terms** (Kapeli/feeds README) allow the docsets for personal use
  or with Dash or Zeal, and not in other applications without permission.
  `SKILL.md` tells agents this.
- **jsDelivr isn't usable as a docset mirror:**
  - limits: 20 MB per file from GitHub, 50 MB per npm package
  - its acceptable-use policy forbids general file hosting and content the
    publisher has no right to distribute
  - mirroring the docsets anywhere would need Kapeli's permission anyway

## Agent trials

Three runs used only `SKILL.md` and `--help` in a cloud sandbox where the
GitHub API is blocked. Each asked for:
- setup: store at `~/.local/share/dash-docset`, user config
- installing the Git cheat sheet and Python 3
- three lookups (asyncio.gather's `return_exceptions`, undoing a commit while
  keeping changes staged, a full-text search for "context variable")
- one note

| Trial | Install | Lookup output | Main findings |
|---|---|---|---|
| 1 (after the plan) | 3 failed attempts plus an out-of-skill curl to find the feed name `Python` | ~130 lines | unhelpful not-found errors; a silently partial `sources`; fts REF format didn't match the docs; silent outputs |
| 2 (`5adc973`) | first try with prefixes | ~230 lines | fts REFs pointed to unrelated entries; navigation chrome in pages; fuzzy hits unmarked |
| 3 (`dc640e3`) | first try, no warnings | ~175 lines | one wrong fts anchor (literal brackets in the docs); notes on `search`; doc mismatches |

A second set of trials used an obscure user-contributed docset, Solarus 1.6.0
(a game engine's Lua API, 837 entries), on the sandbox path (2B, nothing
persists). Sonnet and Haiku ran at default effort, and both got all three
answers right:
- (a) a timer repeats when its callback returns `true`; a timer owned by an
  enemy is canceled when the enemy is hurt, immobilized or restarts
- (b) `enemy:set_attack_consequence("arrow", "protected")`
- (c) the hero's default walking speed is 88 pixels per second

Each used about 190 lines of output for lookups. Haiku's note heading
`## sol.timer.start` silently matched nothing, because entry names include
their arguments, which led to `32b9fad`. The Haiku rerun used about 160
lines and found unquoted multi-word queries failing, which led to `bcc0085`.

A Haiku trial on DuckDB 1.5.0 (user-contributed, 8,208 entries, many
generic "Syntax"/"Parameters" headings) used the desktop path 1B → 1C. It
answered all three questions correctly:
- (a) `date_diff` = 2 vs `date_sub` = 1 months for 1992-09-15 → 1992-11-14
- (b) `read_csv` `skip`: BIGINT, default 0
- (c) `count_if`, an alias of `countif`

It used about 320 lines, the most of any run. About 80 were a parameters
table it needed, and 40 a page it opened by mistake.

Haiku at default and at low effort ran the same task on the Arm Morello A64
ISA (user-contributed, 3,905 entries, CHERI capability instructions). Both
answered all three questions correctly:
- the `SCBNDS`/`SCBNDSE` exact-bounds difference
- `GCBASE` syntax and CSP for register 31
- encoding bit positions, inferred from a rendered bit table

| | Default | Low |
|---|---|---|
| Lookup output | ~130 lines | ~230 lines |
| Path | direct | explored more |
| Bit positions | flagged its answer as an inference | stated without a caveat |
| Notes | correct first time | first wrote a claim from memory, then corrected it |

Both flagged the mismatch between the source name and the installed name,
and the fuzzy noise.

The "keep changes staged" question can't be answered from Kapeli's Git cheat
sheet, which has no `reset --soft`. That's a content gap, not a skill bug.

## Open

- **Waiting on Kapeli:** a reply about the docset terms and redistributing
  the metadata. Bundling starter lists in `assets/` and merging both wait for
  it.
- **Not tested on real machines:**
  - macOS and Windows
  - real Dash/Zeal installs, including the macOS plist key, the Windows
    registry lookup and Zeal's menu path
  - the GitHub API listing (blocked in the sandbox; the fallbacks covered it)
- **`TODO.md`:**
  - semantic search
  - MCP mode (look at ZDocsetMCP first)
  - installing into Dash, Zeal or dasht folders on request
  - optional tarix storage for our own installs
  - a separate `gen-docset` skill
  - the items deferred from the final review
