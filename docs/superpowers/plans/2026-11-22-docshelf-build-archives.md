# docshelf-build archive downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Sphinx builds use a site's published HTML archive when one exists, page-by-page otherwise (TODO 8.13).

**Architecture:** A new `scripts/build_archive.py` (find, download, safe unpack, locate the build folder); `build_plan.py`/`docshelf_build.py` store and use `plan["archive"]`; `build_detect.py` prints it.

**Tech Stack:** Python 3 stdlib (`zipfile`, `tarfile`, `urllib`), `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-22-docshelf-build-archives-design.md`

## Global Constraints

- Stdlib only; no network in tests (fake opener; archives built in the test with `zipfile`).
- Caps: 500 MB unpacked (`MAX_UNPACKED = 500 * 1024 * 1024`), 50,000 files (`MAX_FILES = 50000`); over a cap: `CLIError(..., 2)`, nothing left in `site/`.
- Unpack skips: absolute names, names with a `..` part, symlinks/hardlinks/devices, anything not a regular file or directory.
- All HTTP through the existing `Source`/opener (robots.txt honoured, User-Agent); a HEAD falls back to GET when the opener cannot do HEAD (the fake opener is GET-only: allow an optional `method` path or treat HEAD as GET of headers, implementer's choice, documented).
- Version stays 0.4.0. Public repo rules. Commit trailers as before; branch `update/docshelf-build`; do not push.

## Review Focus

1. A zip with `../evil`, `/etc/x`, a symlink entry, or a zip bomb (many small files or one huge one): nothing outside `site/`, abort over caps, no partial `site/`.
2. Archive missing some inventory pages: those pages fetched over HTTP; summary counts both.
3. API unreachable or returning no `htmlzip`: plan works as today, no warning noise.
4. Rebuild: archive not downloaded again when unchanged; downloaded again on `--refetch` or a changed `Content-Length`/`Last-Modified`.
5. `--no-archive` forces page-by-page.

---

### Task 1: `build_archive.py`

**Interfaces (produces):**
- `find_archive(site_url: str, get: Callable[[str], Tuple[int, bytes]]) -> Optional[str]` — RTD API first (slug from host/`projects/<sub>`), then the `_/downloads/<lang>/<version>/htmlzip/` probe; `None` when none.
- `fetch_archive(url, dest_dir, source, refetch: bool) -> Tuple[str, bool]` — path of the archive file, whether it was downloaded now; keeps `archive.json` (`url`, `size`, `last_modified`, `sha256`) beside it for the change check.
- `unpack(archive_path: str, out_dir: str) -> str` — safe unpack (caps, skips), returns the build folder (holds `objects.inv`, else top folder with `index.html`); raises `CLIError(..., 2)` on caps or no build found.

- [ ] Tests first (class `ArchiveTests`): API answer with htmlzip / without / unreachable then probe 200 / probe 404; traversal, absolute, symlink, too many files, too big (patch the caps small); build folder found one level down; `fetch_archive` skips when unchanged, downloads on `refetch` and on a changed size. RED, implement, GREEN, full suite OK, commit `docshelf-build: archive find, fetch and safe unpack`.

### Task 2: plan, build, detect, docs

**Interfaces (consumes):** Task 1's three functions; `make_plan`, `summarize`, `do_plan`, `do_build`, `open_source`, `fetch_pages`, `build_detect.describe`.

- `plan` (Sphinx URL source): `plan["archive"] = find_archive(...)` (kept across re-plans by recomputing); summary line `archive: URL` when set.
- `build NAME [--no-archive]`: with an archive, read full pages from the unpacked build folder (a local `Source` on it), fall back to the HTTP `Source` for pages missing there; stub links unchanged (`live_base` the site). Print `N pages from the archive, M over HTTP`.
- `detect`: extra `archive: URL` line (Sphinx only).
- Docs: `BUILD-sphinx.md` short paragraph (archive used automatically, `--no-archive`, `--refetch`); AGENTS.md entry one sentence (archives are delivery, not a type; the user, 2026-11-22); TODO 8.13 `[x]`.
- [ ] Tests (class `ArchiveCliTests`): fake site with inventory + an htmlzip lacking one page: build fetches exactly that one page over HTTP and no other page URL; `--no-archive` fetches all pages; plan summary and detect print the archive line; no archive: behaviour unchanged (existing CliTests pass). RED, implement, GREEN, full suite OK, commit `docshelf-build: use a site's HTML archive when it has one`.

### Task 3: live check (controller)

Build `https://www.sphinx-doc.org/en/master/` (needs its host allowed) with and without the archive; compare page counts, request counts and time; note in the PR.
