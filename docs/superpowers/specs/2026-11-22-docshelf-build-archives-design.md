# docshelf-build: archive downloads as a delivery layer (TODO 8.13)

Date: 2026-11-22. Approved by the user ("approach B").

## Intent

When a Sphinx docs site publishes its whole HTML build as one archive, fetch
that once instead of hundreds of pages. An archive is a delivery mechanism,
not a new site type: types come from metadata and organization (the user,
2026-11-22). So it lives under the fetch layer, transparently.

## Facts (2026-11-22, Read the Docs API)

`readthedocs.org/api/v3/projects/<slug>/versions/<version>/` lists
`downloads`. Of requests, pip, sphinx, attrs, flask only sphinx offers
`htmlzip` (`https://www.sphinx-doc.org/_/downloads/en/latest/htmlzip/`). The
archive is the exception: a fast path with a page-by-page fallback.

## Design

- **plan (Sphinx URL source):** look for an HTML archive. Host
  `<slug>.readthedocs.io` (or `<slug>.readthedocs.io/projects/<sub>/`) gives
  the slug: ask the API for `downloads.htmlzip` of the version in the URL path
  (`/<lang>/<version>/`). Otherwise, or when the API is unreachable, send one
  HEAD (falling back to GET) to `<site root>/_/downloads/<lang>/<version>/htmlzip/`.
  Found: store `"archive": URL` in the plan and print `archive: URL` in the
  summary. Not found: nothing changes. Re-plans keep looking.
- **build:** with `plan["archive"]` and no `--no-archive`: download it once to
  `<cache>/built-src/<name>/archive.zip`, unpack safely into
  `<cache>/built-src/<name>/site/`, find the folder holding the build (the one
  with `objects.inv`, else the top folder with `index.html`), and read the full
  pages from disk. Pages missing from the archive are fetched over HTTP as
  today. Stub links still point at the live site. A rebuild downloads the
  archive again only on `--refetch` or when a HEAD shows a different
  `Content-Length` or `Last-Modified` from the stored ones. The build summary
  says how many pages came from the archive and how many over HTTP.
- **Safe unpacking:** zip (and `.tar.gz`/`.tgz` if a URL ends so): skip
  absolute names, `..` parts, links and anything not a regular file; over
  500 MB unpacked or 50,000 files the unpack fails with nothing written
  (no `site/`). `build` then skips the archive with a warning and fetches
  page by page, as it does for an archive that cannot be downloaded or
  unpacked at all (corrupt, wrong format) (controller ruling, 2026-11-22).
- **detect:** prints `archive: URL` as an extra line when found; the type
  stays `sphinx`.
- **Docs:** `BUILD-sphinx.md` one short paragraph; `SKILL.md` no change;
  AGENTS.md entry one sentence; TODO 8.13 done.
- Version stays 0.4.0 (unmerged, same PR #33).

## Non-goals

llms.txt archives, PDF/ePub, archives from other hosts than the site's own
(or Read the Docs'), using the archive's own `objects.inv` instead of the
live one.

## Approaches

A. Archive as an explicit SOURCE plus a `detect` hint (rejected by the user:
an archive is delivery, not type). **B. Transparent fast path in plan/build
(chosen).** C. Do nothing.
