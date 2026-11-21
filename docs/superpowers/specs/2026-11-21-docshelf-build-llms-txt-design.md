# docshelf-build: llms.txt sites (0.2.0)

TODO 8.9. Extends `docshelf-build` 0.1.0 (Sphinx `objects.inv`, spec
`2026-11-21-docshelf-build-design.md`) with a second source type: sites that
publish an `llms.txt` page list (Mintlify, Astro Starlight, opencode,
LangChain and many others).

## Intent

Agents want dense reference, not tutorials (the user, 2026-11-21). The Sphinx
builder can tell the two apart from inventory roles; an `llms.txt` file
cannot, it only lists pages under free-form section headings. So this build
**errs on the side of fetching too much** (the user, 2026-11-21): every
listed page is fetched and stored. Excess can be measured and trimmed later;
a missing page can only be judged by fetching it anyway. Sorting reference
from guide is left to a later classifier step that edits the plan.

The build must make that later step cheap: keep the raw downloads so a
re-sort costs no network, and record simple evidence per page.

## Goals

- `plan` and `build` accept an `llms.txt` URL (or a sub-index URL) as SOURCE.
- Follow nested indexes (LangChain's `llms.txt` links `/_llms/*.txt`
  sub-indexes, about 1,800 pages): the plan summary shows the index tree
  with page counts before any page is fetched, so the user can narrow with
  `--stub` globs or by passing a sub-index as SOURCE.
- Every listed page starts `keep: full`, including `## Optional` and
  marketing pages (`why: "llms: all"`).
- Fetch each page's Markdown, convert it to HTML with the standard library,
  and write the same docvol files as the Sphinx path (`index.json`,
  `db.json`, `meta.json`, `"format": 1`). No docshelf change needed.
- Keep each raw download in a page cache; rebuilds reuse it unless asked to
  refetch.
- Record cheap signals per fetched page in the plan.

## Non-goals

- No classifier inside the skill (embedding model, decision model): it
  would break "standard library only". It is a separate later step that
  rewrites `keep` and sets `why: "model:<id>"` (the field already allows
  it).
- No crawling of sites without `llms.txt`; no `llms-full.txt` reading
  (possible later as a one-download source).
- No authentication, no JavaScript rendering.

## Anti-goals

- Silently dropping pages: anything listed is either stored or a stub with a
  live link, never missing.
- Re-downloading a whole site to re-sort it.
- A Markdown converter that loses code blocks, links or headings; those are
  what agents use.

## Approaches considered

1. **Fetch everything, keep raw pages, classify later** (picked by the
   user). Simple, honest about uncertainty, gives labeled-later data.
2. Heuristic stubs now (section names like "Guides", "Tutorial", words in
   URLs). Rejected: contradicts "fetch too much", and wrong guesses hide
   pages nobody then checks.
3. Classifier inside the build. Rejected: adds a model dependency to a
   stdlib-only skill and couples two things that change at different rates.

## Design

### Source detection

SOURCE is an `llms.txt` source when it is a URL whose path ends in `.txt`
(e.g. `https://opencode.ai/llms.txt`, `https://docs.langchain.com/_llms/python.txt`),
or a local `.txt` file (for tests and offline indexes; page links are then
fetched from their absolute URLs). Anything else keeps the Sphinx path. The
plan records `"kind": "llms"` (Sphinx plans get `"kind": "sphinx"`; a plan
with no `kind` is Sphinx).

### Reading llms.txt

Format (llmstxt.org): `# Title`, optional `> summary` blockquote, optional
prose, then `## Section` headings each followed by a list of
`- [title](url)` items with an optional `: note`. Parse leniently:

- Link lines anywhere (also `* ` bullets, nested bullets) count; a link
  before any `##` heading gets section `None`.
- A link whose URL path ends in `.txt` on the same host is a **sub-index**:
  fetch and parse it the same way, recursively, depth limit 3, each index
  once. Its pages get section `"<parent section> / <sub-index title>"`.
  Sub-indexes on other hosts are listed in the summary but not followed.
- Other links are pages. Relative URLs resolve against the index URL.
  Duplicate URLs keep the first occurrence.
- The note after `:` becomes the page `description` (shown on stubs).

### Page keys

Keys must stay the same when the index changes or a sub-index is chosen as
SOURCE, because overrides, manual and model choices, docvol paths, notes
and the page cache all hang on them (my call, after the builder check).
So the key is the URL's full path from the **host root**, not from a common
directory: strip the leading `/`, then `.md`, `.mdx`, `.html`, `.htm`; a
trailing `/` becomes `/index`, e.g. `https://opencode.ai/docs/build.md` ->
`docs/build`. The **main host** is the host of the SOURCE URL; for a local
`.txt` SOURCE, the host most page links use (ties: first seen). Pages on
other hosts: `<host>/<path>`. The key is a pure function of the URL, so
collisions only come from the same path with different extensions; on one,
the later URL in listing order gets `-2`, `-3` (rare; warn). Store `uri` =
the absolute URL as listed.

### Plan

Same file and fields as 0.1.0 (`<cache>/built-plans/<name>.json`): per page
`keep`, `title` (link text), `section`, `description`, `why`, `uri`, plus:

- top level: `"kind": "llms"`, `"index_sha256"` (of every index fetched,
  root and sub-indexes, concatenated in visit order),
  `"indexes"`: list of `{url, title, pages, parent}` for the tree,
  `"rule": "llms-all"`.
- per page, after a build: `"signals"` (below) and `"fetched"` (ISO time),
  `"fetch_error"` when the last attempt failed.

`--full`, `--stub`, `--all`, `--reset` and `"manual"` behave as in 0.1.0.

Re-planning keeps what only later steps know (my call, after the builder
check): a page whose old `why` starts with `model:` keeps its `keep`,
`description` and `why`, like a `"manual"` page; overrides given on the
command line still win over it, and `--reset` drops it. `signals`,
`fetched` and `fetch_error` are always carried over for pages still
listed. Apply the same `model:` rule to Sphinx plans, since the classifier
is meant for both.
The globs match page keys. `project` = the H1 title, `version` = `""`.
Name default: slug of the H1 (`derive_name` rules), e.g. `opencode`.

### Summary (plan and build)

```
opencode: 33 pages: 33 full, 0 stub
  Docs: 18   Optional: 6   Products: 4   Console: 3   Site: 2
index tree:
  llms.txt (33)
```

For a nested site, the tree lists each sub-index with its page count, so
the user sees `_llms/python.txt (240)` before choosing. Over 300 full pages,
warn and suggest narrowing (SOURCE = a sub-index, or `--stub` globs);
do not refuse.

### Fetching

`build` first re-reads the whole index tree (index files are small: one
request each) and, when `index_sha256` differs, re-plans as `plan` would
(keeping overrides, manual and model choices) and prints what was added
and dropped. This is how a rebuild learns of new pages (my call, after the
builder check). Pages are then fetched as below; a rebuild from a warm
cache makes index requests only, no page requests.

Reuse `build_fetch` (User-Agent, robots.txt, retries, one worker default,
0.5 s delay). For each `full` page:

1. If a cached raw copy exists and `--refetch` is not given, use it.
2. Otherwise GET the listed URL. If the URL does not end in `.md`/`.mdx`
   and the body looks like HTML (starts, after whitespace, with `<!doctype`
   or `<html`, case-insensitive), try once more with `.md` appended (Mintlify
   serves both); if that fails too, keep the HTML.
3. Store the raw body in the page cache.

A failed page keeps its previous cached copy and docvol content (as in
0.1.0) and gets `fetch_error` in the plan.

### Page cache

`<cache>/built-src/<name>/` holds one file per page key (`<key>.md` or
`<key>.html`, folders as in the key) plus `manifest.json`
(`{key: {url, sha256, fetched, type}}`). Written atomically per file.
`remove NAME` deletes it too; `remove NAME --plan` also the plan.
Stub pages keep their cached copy, so turning a page back to `full`
rebuilds it with no download.

### Markdown to HTML (`build_markdown.py`, stdlib)

A block-level converter good enough for documentation, not full CommonMark:

- YAML front matter (`---` ... `---` at the top): `title` and `description`
  fill the page title and description when the index gave none; then
  dropped.
- MDX: lines starting `import ` or `export ` at top level are dropped.
  JSX/MDX components (tags whose name starts with a capital letter, e.g.
  `<Card>`, `<CardGroup cols={1}>`, `<Tabs>`, `<Note>`) are removed, their
  inner text kept. A component with `href` and `title` attributes becomes a
  link `<a href>title</a>`; a component with only `title` becomes a
  `<p><strong>title</strong></p>`. Attribute values may be `"..."`,
  `'...'` or `{...}`.
- ATX headings `#`-`######` (with ids from the text, `anchor_id` rules,
  unique per page); setext headings.
- Fenced code (```` ``` ```` and `~~~`, with info string ->
  `class="language-<lang>"`), indented code, inline code; code is never
  further parsed.
- Paragraphs, hard breaks, emphasis, strong, links, autolinks, images (->
  alt text, as 0.1.0 does), bullet and ordered lists (nesting by indent),
  blockquotes, horizontal rules, GFM pipe tables.
- Raw lowercase HTML passes through, then the whole page goes through the
  existing `_serialize` (drops scripts, styles, forms, iframes).

HTML pages (step 2's fallback) go through `main_content` as Sphinx pages do.
Then `rewrite_links` maps links to other stored pages to relative docvol
paths (keys by URL, with and without `.md`), other same-site links to live
URLs, and leaves external links.

### Index entries

No inventory roles, so entries come from the converted page: one entry per
page (its title, path = key) and one per `h2` and `h3` (the heading text,
path = `key#id`). Entry `type` =
the page's section (top-level part, e.g. `Docs`, `Optional`), or
`Pages` when it has none. Stub pages get their page entry only.

### Signals

Computed from the raw Markdown (or the HTML's text) at build time, stored
under `pages.<key>.signals`:

- `words`: word count outside code.
- `code_ratio`: lines inside code blocks / non-blank lines.
- `you_per_1k`: "you", "your", "let's", "we'll" per 1,000 words.
- `steps`: ordered-list items plus headings starting "Step".
- `signature_lines`: lines in code or headings that look like a
  declaration (`name(`...`)`, `def `, `class `, `function `,
  `interface `, `type X =`, a `-`/`--` option at line start).
- `headings`: count of `h2`/`h3`.
- `tables`: count of tables.

Recorded only; they change nothing in 0.2.0. A later classifier (cheap
thresholds, an embedding classifier trained on Sphinx-built role labels, or
a decision model) reads them and writes `keep` and `why: model:<id>`.

### Command line

```
docshelf_build.py plan  SOURCE [--name N] [--full PAT] [--stub PAT] [--all] [--reset]
docshelf_build.py build SOURCE [same] [--workers N] [--refetch]
docshelf_build.py list | remove NAME [--plan]
```

`--base-url` is Sphinx-only (an error with an `llms.txt` SOURCE).
`--refetch` applies to both kinds (Sphinx: ignored, it has no page cache;
say so in help).

### meta.json

As 0.1.0 plus `"source_kind": "llms"`. Format stays 1: docshelf ignores
unknown keys (confirm in `shelf_*` when implementing; if it does not, add
nothing and keep the kind in the plan only).

## Version and files

- `metadata.version` and `build_core.VERSION` -> `0.2.0` (minor: new
  feature). Branch `update/docshelf-build`, PR, merge commit.
- New: `scripts/build_llms.py` (index parsing, tree, keys),
  `scripts/build_markdown.py` (converter, signals).
- Changed: `build_plan.py` (llms plan), `build_fetch.py` (`.md` retry,
  page cache), `build_docvol.py` (entries from headings, `source_kind`),
  `docshelf_build.py` (dispatch, `--refetch`), `SKILL.md` (llms.txt usage,
  short), `AGENTS.md` skill entry, `TODO.md` (8.9 done; classifier as a new
  item).
- Tests in `tests/test_docshelf_build.py`: fixtures for a flat index
  (opencode-like, with JSX), a nested index, Markdown conversion cases,
  cache reuse (rebuild requests index files only), stable keys when a
  sub-index is the SOURCE, `model:` choices surviving a re-plan, `.md`
  retry, signals, robots,
  failure keeps old copy. No network.

## Left to the builder

- Internal structure of the converter (line-based block parser recommended).
- Exact wording of summaries and warnings.
- Whether `plan` fetches sub-indexes in parallel (keep one worker default).
