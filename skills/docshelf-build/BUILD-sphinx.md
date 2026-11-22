# Sphinx sites (objects.inv)

For sites that publish `objects.inv`: Sphinx, Read the Docs, PyDoctor,
MkDocs with mkdocstrings. `detect` prints the SOURCE: the folder that holds
`objects.inv`, a site URL or a local HTML build (`_build/html`). `detect`
has already checked the inventory: pass its SOURCE straight to `plan`.

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

For a local build, `--base-url URL` gives the live site, so stubs link to
it instead of to nothing.

A warning that no page has a domain role means the site is all prose: keep
the groups you need with `--full`, or the docvol is stubs only.

Sphinx builds have no page cache: a rebuild downloads the full pages again.
Exit code 3 means SOURCE has no Sphinx inventory.
