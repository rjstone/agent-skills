# llms.txt sites

For sites that publish `llms.txt`, a Markdown list of page links (Mintlify,
Astro Starlight and others). SOURCE is the `llms.txt` URL that `detect`
prints; a sub-index URL or a local `.txt` file also works.

Every listed page is kept in full; nothing becomes a stub unless you ask
(`--stub PAT`). Sub-indexes (`.txt` links) on the same host are followed
three levels deep; `*-full.txt` dumps are listed but not followed. Page keys
come from the URL path, so a page has the same key whichever index is the
SOURCE.

## The loop

1. `plan SOURCE --name NAME` prints the index tree and page counts. A large
   site (over 300 full pages warns) is worth narrowing before building:
   plan a sub-index as SOURCE with its own `--name`, or add
   `--stub 'group/*'`. Patterns are shell globs on page keys, later ones
   win, and they are kept in the plan (`--reset` clears them).
2. `build NAME` downloads the pages (one request at a time, robots.txt
   honoured) into a page cache (`built-src/NAME` in the docshelf cache) and
   writes the docvol. A page served as HTML is retried at its `.md` URL. A
   page that fails keeps its cached copy, or becomes a stub with the error,
   and the plan records `fetch_error`.
3. Look things up with docshelf: `search WORDS -d NAME`, `show NAME:PAGE`.

`build SOURCE --name NAME [plan options]` does 1 and 2 in one step. Plan
options go with `plan` or with a SOURCE, never with `build NAME`.
`--base-url` is for Sphinx only.

## Rebuilds

- `build NAME` reuses the page cache; `build NAME --refetch` downloads the
  pages again.
- If the index changed, `build` re-plans and prints what was added and
  dropped.
- `remove NAME` deletes the page cache with the docvol.

## Sorting reference from tutorials

Each page's plan entry holds `signals` (word count, code ratio, signature
lines, "you" per 1000 words and similar counts), recorded by `build`. The
loop:

1. `build NAME` (fills the signals and the page cache).
2. `classify NAME` applies the rules (`why: "model:rules-1"`), prints one
   count line, then up to 25 review pages (`--offset K`, `--limit N`) with
   signals and a short preview from the cache.
3. Write one line per review page to a file: `full KEY` or
   `stub KEY [short description]`. Pages you leave out stay in full.
4. `classify NAME --apply FILE --model YOUR_MODEL_ID` (`-` reads stdin);
   it stores `"why": "model:<id>"` and reports skipped lines.
5. `classify NAME` again, until it says nothing is left to review.
6. `build NAME` (no page downloads: the cache is used).

The rules never touch a page a person decided (`manual`, `override:`) or an
agent decided (`model:<id>`). Add patterns with `plan SOURCE --full/--stub
PAT`, not by editing the plan: a hand-edited pattern loses to an earlier
choice. A choice survives re-planning; `plan --reset` drops the agent's
choices, and `classify` brings back the rules' part but not the agent's.
