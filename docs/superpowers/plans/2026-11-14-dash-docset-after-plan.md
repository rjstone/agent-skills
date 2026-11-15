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
| `17aa682` | Progressive disclosure: `SKILL.md` keeps only lookups (`search`, `show`, `fts`, scope) and Kapeli's terms, 9.3 KB → 3.3 KB. First-run setup and "Other options" moved to `references/setup.md`, sources/install/update/remove and the allowlist to `references/installing.md`, notes authoring to `references/notes.md`. The "location not set" error now points agents to `references/setup.md`, since the "user chooses the location" rule no longer sits in `SKILL.md`. | the user, 2026-11-15: cut the per-session token cost |
| `e0517c4` | Plain `where` with no location set also points agents to `references/setup.md` (it had its own message). | token trial 1 |
| `5288a6c` | `show --grep TEXT` (matching lines plus heading and table header row); `fts` prints 5 hits by default and its cut line says to add words; `search` folds a whole-page entry into the anchored entry with the same short name on the same page, as `(also REF)`, and drops the repeated `(Docset)` suffix; `setup.md`: throwaway machines skip `--discover`. | token trial 1 |
| `8f30f0b` | `show --grep` ends with "(all N lines containing 'X' are shown; the section has M lines)"; `search` prints `(same section: REF)` (JSON `same_section`) instead of `(also REF)`, and `SKILL.md` says not to open those. | token trial 2 |
| `e19861e` | `show` prints `(page: Title)` before a section whose heading isn't the page's own (DuckDB's `## Parameters` is on "CSV Import"); folded same-section REFs appear only in `--json` (`same_section`); the `fts` cut line says "more hits cut" without a count. | token trial 3 |
| `8988b73` | Top-level `--help` is the command reference: usual command lines with a few words each, then each subcommand's other options named only, generated from the parser (`COMMON_OPTIONS`). `SKILL.md` defers syntax to it (2.9 KB). Tests: every option appears once in the help; docs name only real flags. | the user, 2026-11-15: avoid drift and subcommand `--help` reads |
| `c8cc0fb` | Repeated page footers: trailing blocks that ≥60% of up to 40 sampled pages end with exactly are left out of `show` and the fts index on every page but one (the index page if an entry points to it, else the first entry's page), so fts finds them once. Found: Morello 8 blocks (368 chars), Python's copyright line (442), Solarus's doxygen line (28); none in DuckDB or Git. Supersedes "navigation footers are left alone" (`b30f065`): an exact repeat isn't a guess. `FTS_FORMAT` 2 rebuilds older indexes. `notes --check` prints "notes file present", which REFs show each section (headings as written), then "ok"; a missing file is "notes file not present" for `notes` and `--check`. `notes.md`: General is optional. | the user, 2026-11-15, from trials 7-9 |
| `f9763f5` | User-Agent `docset-agent-skill-RJS/<VERSION>` (was `dash-docset/<VERSION>`), unambiguous so Kapeli could filter or rate-limit it. `search` prints the hidden-fuzzy line only when no hit holds the query as whole words. | the user, 2026-11-15 |

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

### Token trials (2026-11-15)

Goal: measure the output agents don't need (the user, 2026-11-15). Haiku at
default effort, sandbox path 2B, DuckDB 1.5.0, a trial copy of the skill whose
`scripts/docset.py` wrapper logged every call's output. Questions: `date_diff`
vs `date_sub` months (2 vs 1, `DuckDB:5097`/`5099`); `read_csv` `skip` (BIGINT,
default 0, a row of `DuckDB:29`); `count_if(42)` (1; a non-zero number counts
as true, `DuckDB:6072`); plus one note. The earlier DuckDB trial's "count_if
is an alias of countif" isn't in this docset (two separate entries), so that
question was replaced. Sizes are characters (tokens ≈ chars / 4).

| | Run 1 (`17aa682`) | Run 2 (`5288a6c`) | Run 3 (`0ad3513`) | Run 4 (`aff6dae`) | Run 5 (`a3315ed`) |
|---|---|---|---|---|---|
| Answers | all correct | all correct | all correct | all correct | all correct |
| References opened | setup, installing, notes, each at its trigger | same | same | same | same |
| All script output | 14,620 | 13,631 | 6,192 (−58%) | 6,631 (−55%) | 6,370 (−56%) |
| `search`/`show`/`fts` output | 11,417 | 9,911 | 3,679 (−68%) | 3,040 (−73%) | 3,262 (−71%) |
| Biggest call | `show DuckDB:29`, 5,551 (a whole parameters table) | `show DuckDB:29` without `--grep`, 6,658 | `--help`, 1,107 | `--help`, 1,107 | `--help`, 2,151 |

Run 1, lookup output against the answer spans: ~11% needed, ~40% irrelevant
(`fts skip` hit at rank 7 of 17, a wrong Python-API page, overloads, a
duplicate entry), ~49% excess (the whole table for one row).

Run 2 used `fts read_csv skip` (right page first) and `show DuckDB:29 --grep
skip` (385 chars), then reran `show DuckDB:29` without `--grep` "to confirm
no second skip row was hidden" by the `...` gaps, and opened the `(also)`
duplicate "to check it wasn't different text". Without those two calls the
lookups would have been ~3.1k (−73%). Both were confirmation calls; the
output didn't say that `--grep` shows every match, or that `(also)` entries
are the same text.

Run 3: no unfiltered rerun. Two confirmation calls remained: a second
`show DuckDB:29 --grep "Alias for delim"` (401) to check the table was
`read_csv`'s, because the section heading is only "## Parameters"; and
`show DuckDB:6122` (158) despite "(same section: ...)" and the `SKILL.md`
line saying not to open those.

Run 4: one `show` per answer, no confirmation calls. `--help` output (top
level plus `where`, `sources`, `install`, `notes`) varied from 1.5k to 2.8k
between runs and is now the largest overhead (42% of run 4's output). Haiku
again read a note written as `## count_if` shown as `## count_if(x)` and
wasn't sure it had matched (run 1 too).

Run 5 (top-level `--help` as the command reference): no subcommand `--help`
at all; help output 2,151 (one call) against 1.5k-2.8k before. `SKILL.md`
3.5k → 2.9k. One small confirmation call remained (`--grep "Number of
lines"`, 235). Haiku displayed and matched the `## count_if` note heading
without confusion this time.

Run 6: Haiku at **low** effort on `a3315ed`, same task. All answers
correct, the same four references at their triggers, 19 calls. Output 7,090
(lookup 3,616, help 2,675: it also read `where --help`), about 10% more than
run 5 at default effort. One confirmation call (`--grep Number`), which it
called wasted itself. Unlike the Morello low-effort trial (which explored
more), low effort barely changed the path here.

Runs 7-9: Haiku at default effort on `d312b10` with the other docsets, three
questions plus a note each, rewritten from the earlier trials (Git: `git reset
--keep <commit>`, `Git:68`, instead of the unanswerable `reset --soft`). All
answers correct; the same three references opened at their triggers.

| | Python 3.15 + Git cheat sheet | Solarus 1.6.0 | Morello 2022.01 |
|---|---|---|---|
| Calls | 23 | 23 | 16 |
| Lookup output | 9,598 (169 lines) | 9,575 (101 lines) | 10,066 (145 lines) |
| Earlier trials (lines) | 130-230 | 160-190 | ~130 |
| Biggest call | `show Python:7368` (gather, 52 lines), 3,116 | `show solarus:803` (timer.start), 3,177 | `show arm64morello:2131`, 2,293 |

Not worse than before, but about 3x DuckDB's 3.3k: these answers sit in long
sections that agents opened whole before knowing which lines mattered.
Repeats seen in every run, DuckDB included: after writing a note, a `show`
of the entry to confirm the note appears (Morello twice, 3.6k; Python three
variants). Morello's identical page footer (instruction-set links,
proprietary notice, copyright; ~400 chars) is printed by every `show`.

Reruns 10-11 on `c9e1f56` (footer stripping, `notes --check` listing which
REFs show each section), same prompts. All answers correct.

| | Python + Git before → after | Morello before → after |
|---|---|---|
| Calls | 23 → 17 | 16 → 17 |
| All script output | 13,441 → 12,833 | 13,176 → 9,405 (−29%) |
| Lookup output | 9,598 → 8,454 | 10,066 → 5,986 (−41%) |
| `show` after `notes --check` | 3 calls, 2,346 → 1 call, 624 | 2 calls, 4,081 → 1 call, 1,826 |

Morello `show` output no longer has the footer (`show arm64morello:2131`:
1,788 → 1,412 without notes). The remaining confirming `show` in each run
came while revising the note (Morello) or checking its wording (Python), not
to see whether it matched. Haiku called the `... N fuzzy matches hidden`
line noise on exact-name searches (Python: ~1,450 hidden).

Semantic search (embeddings) is dropped from `TODO.md` (the user,
2026-11-15): after these changes, irrelevant hits are a small share of lookup
output, and agents already rephrase queries for `fts`, so an embedding index
(a dependency or a network service) wouldn't pay for itself.

`SKILL.md` + the three references read on a first run: ~9.9k, about the old
single `SKILL.md`; later sessions read only `SKILL.md` (~3.5k).

### Trials with other models in opencode (2026-11-15)

Goal: see how the skill holds up with non-Anthropic models, mostly ones
cheaper or weaker than Haiku (the user, 2026-11-15). Harness: opencode 2.3.0,
`opencode run`, one isolated home per model holding only this skill. The
prompts never name the skill. Each run happened once, so single results are
anecdotes; patterns across models are the finding. How to run them again is
at the end of this section.

Models (sizes are total parameters from the Hugging Face model pages unless
marked; "by name" means taken from the model's name only):

| Model | Provider | Size |
|---|---|---|
| `liquid/lfm-3-1.7b:free` | OpenRouter | 1.7B |
| `nvidia/nemotron-3.5-lightning:free` | OpenRouter | 30B, 3B active (by name) |
| `ricursiveai/ripple-65b-preview` | Nous | 65B (by name) |
| `qwen/qwen3-next-80b-a3b-instruct` | Nous | 80B, 3B active (by name) |
| `nvidia/nemotron-3-super-120b-a12b` | Nous | 120B, 12B active (by name) |
| `nvidia/nemotron-3.5-super-vl:free` | OpenRouter | 124B, 12B active |
| `stepfun/step-3.7-flash` | Nous | 201B |
| `mimo-v2.6-flash` | OpenCode Go | 311B |
| `Beam-1.0-501B-A23B` | Reflection | 501B, 23B active |
| `deepseek-v4.1-flash` | OpenCode Go | 763B |
| `gpt-6-luna`, `muse-spark-1.3-contributor` | OpenCode Go | not published |

Not usable from the sandbox: OpenCode Zen's free models ("Free usage limit
reached" on every one) and Nous's `stepfun/step-3.7-flash:free` (each run
stalled after its first tool call; the paid model ran normally).

**Round 1, set `basic`, skill at `6c8e344`.** Four scenarios against a
project whose store already held Jinja, the Git cheat sheet and Pandas: S1 a
`read_csv` option (needs page text), S2 a Jinja signature, S3 a lookup in a
docset that must be installed first (Flask), S4 a cold start with no store.

| Model | Loaded the skill | S1-S3 |
|---|---|---|
| Luna, Muse Spark, DeepSeek flash, MiMo, Beam, Step 3.7 Flash | 4 of 4 runs | all correct with the script |
| `lfm-3-1.7b` | 3 of 4 | right answers by grepping the docset's HTML; copied `PATH` and `QUERY` from the help text literally; read the whole script instead of `--help` |
| `nemotron-3.5-lightning` (30B) | 0 of 4 | S1-S2 right by grepping HTML (S1 at 77k input tokens; most others 11k-17k); S3 failed, it never found a way to install |

What the runs showed, and what was changed (`b346149`):

- Three models ran `cd <skill folder> && python scripts/docset.py ...`. From
  there the project file wasn't found, so the script said "storage location
  not set" and the model started first-time setup. Now the file is also
  looked for from the script's folder, `OLDPWD` and parent processes'
  folders, and `SKILL.md` says to stay in the project folder.
- `show REF --grep on_bad_lines` printed the one matching line without the
  parameter's description, and four of six models then piped `show` through
  `grep -A`. Now a matching definition term comes with its definition.
- `-d pandas` was rejected (the docset is `Pandas`). Names now match without
  regard to case in lookups.
- Step 3.7 Flash ran `where --discover`, concluded no store was set, and
  ran `where --set .docsets --project` over the existing project file, which
  dropped the installed docsets out of use. `where --set` now refuses to swap
  a store without `--replace`, and `where --discover` prints the store in use.
- S4 can't be judged in `opencode run`: the question tool is cancelled with
  "make reasonable assumptions". Five of the six larger models tried that
  tool first. Luna and Step 3.7 Flash stopped and asked in their reply;
  the other four picked a location.

**Round 2, set `basic` again, skill at `b346149`** (same models without the
1.7B one). All S1-S3 answers correct.

| | Round 1 | Round 2 |
|---|---|---|
| Commands run from inside the skill folder | 12 | 0 |
| `show` piped through `grep` | 7 | 0 |
| Script calls in S1 (Step, DeepSeek, Luna, MiMo, Muse Spark) | 8, 9, 8, 6, 5 | 4, 4, 4, 3, 4 |
| Step 3.7 Flash, S3 | overwrote the project's store | store intact, Flask added |

Beam did not load the skill in S1 this time (it had in round 1), and the
30B nemotron still skipped it in three of four runs.

**Round 3, set `docsets`, skill at `b346149`.** The four tasks of the Haiku
trials above, rewritten (the earlier prompts weren't kept): set up a store,
install the docset, three questions, one note. The prompt names the store
(`.docsets`) and approves it, because the run can't ask. Seven models: the
six from round 1 that used the skill, plus `nemotron-3.5-super-vl` (124B).

- 27 of 28 runs answered all three questions correctly; all 28 loaded the
  skill and attached the note (`notes --check` ok).
- The one wrong answer: Step 3.7 Flash put `GCBASE`'s `Cn` field in bits
  15:11 (it is 9:5, read off the rendered bit table).
- Six of seven models searched several function names at once (`search
  date_diff date_sub`) and got "no matches". Changed in `5bb7fb2`: `search`
  now lists the best entry for each word.
- One model passed `-d` to `show` (a usage error, three calls). Not changed.
- Script output per task: about 6k-20k characters, against Haiku's 6k
  (DuckDB) and 10k (the others).
- The Solarus question "what exact call makes an enemy unaffected by
  arrows" was answered `enemy:set_attack_consequence("arrow", "ignored")` by
  all seven; the earlier trials' answer was `"protected"`. The docset supports
  both ("ignored": nothing happens; "protected": the enemy stops the attack),
  so the scorer accepts either.

**Round 4, set `docsets`, skill at `5bb7fb2`, three smaller models.**

| Model | Result |
|---|---|
| `nemotron-3-super-120b-a12b` | all four tasks done with the skill, notes attached, 11 of 12 answers right; 240k-375k input tokens per task |
| `qwen3-next-80b-a3b-instruct` | no task completed |
| `ripple-65b-preview` | no task completed |

Failures by kind:

- **Invented documentation.** Ripple (Morello) loaded the skill, ran no
  script command, then reported "The docset is installed and the notes are
  attached" with made-up quotes and a made-up reference file. Qwen (DuckDB,
  Solarus) wrote its own `index.html` inside a fake `.docset` folder after
  its web searches were cancelled, and answered "based on this
  documentation" (wrongly: `date_diff` 1, `skip` INTEGER).
- **Never loading the skill.** Qwen in three of four tasks (web search, a
  `dash -install` command, a search for kernel sources); Ripple once (it
  tried `require("dash-docset")`).
- **Loading it but not following it.** Qwen (Python) skipped `--help` and
  the references, wrote its own `.dash-docset.json` with `"docsets":
  ".docsets"`, and made 26 mostly failing calls ("unknown docset '.'") at
  442k input tokens; it then answered from `help()` and put the note in a
  text file, and said so. Ripple (Python) set up and installed correctly,
  guessed syntax twice, and quit without answering.
- **Stopping early.** Ripple (DuckDB) did every lookup and the note
  correctly and ended before writing the answer.
- **Wrong page.** The 120B nemotron answered the `read_csv` `skip` question
  with `skiprows`, `Optional[int]`, default `None`, from DuckDB's Python API
  page (the trap the first Haiku token trial also hit).

With these models the skill worked from about 120B up and not at 80B or
below, but family and training differ as much as size, so that is not a
size rule. Only one of the round-4 failures is something the script could
soften (a message that names the config file when `"docsets"` isn't a
list); the user declined that change (2026-11-15).

#### Running these trials again

Files: `docs/superpowers/trials/dash-docset/` holds `run_trials.sh` (the
prompts are in it), `score_trials.py` and the `opencode.json` that adds
Nous as a provider.

Needs: Linux (on macOS, also GNU `timeout`), `opencode` (v2), `python3`,
network access to the
providers and to the hosts in the skill's `assets/allowlist.txt`, and an
API key for each provider used.

```bash
# from the repo root; set the keys opencode reads for the providers you use
export OPENROUTER_API_KEY=... NOUS_API_KEY=... OPENCODE_API_KEY=... REFLECTION_API_KEY=...
export OUT="$HOME/dash-docset-trials"

T=docs/superpowers/trials/dash-docset
$T/run_trials.sh basic   opencode-go/gpt-6-luna opencode-go/mimo-v2.6-flash
$T/run_trials.sh docsets nous/stepfun/step-3.7-flash "openrouter/nvidia/nemotron-3.5-super-vl:free"
python3 $T/score_trials.py "$OUT"/docsets/*/        # -v: every command and the reply
```

- Model names are `provider/model` as `opencode models` prints them. A Nous
  model must also be listed under `providers.nous.models` in
  `opencode.json` there. A key variable left unset is set to a placeholder,
  which only works where an egress proxy injects the key.
- A run takes 10 seconds to 5 minutes; models run in parallel. The whole of
  round 3 (seven models, four tasks) took about 13 minutes.
- Each model gets its own `HOME` under `$OUT`, with a link to the skill as
  its only skill. Agents still wrote outside it now and then (a folder in
  the temporary directory, an `apt-get install`), so use a throwaway
  machine.
- The scorer's answer checks are patterns over the reply. Read a flagged
  reply before calling it wrong, and read the replies of small models even
  when nothing is flagged: an invented quote can pass a pattern.
- To compare skill versions, check out the commit and run again with a new
  `OUT`; `score_trials.py` prints script calls, errors and output size per
  run.
- Sizes came from the Hugging Face model pages; free models and prices
  from each provider's `/models` endpoint. Both change.

## Open

- **Waiting on Kapeli:** a reply about the docset terms and redistributing
  the metadata. Bundling starter lists in `assets/` and merging both wait for
  it.
- **Not tested on real machines:**
  - macOS and Windows
  - real Dash/Zeal installs, including the macOS plist key, the Windows
    registry lookup and Zeal's menu path
  - the GitHub API listing (blocked in the sandbox; the fallbacks covered it)
- **From the other-model trials, not changed:** `show` rejects `-d`
  (one model tried it); a `"docsets"` value that isn't a list gives
  "unknown docset '.'" (declined); models that never load the skill.
- **`TODO.md`:**
  - MCP mode (look at ZDocsetMCP first)
  - installing into Dash, Zeal or dasht folders on request
  - optional tarix storage for our own installs
  - a separate `gen-docset` skill
  - the items deferred from the final review
