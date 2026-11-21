# Getting docvols

Docvols are DevDocs documentations (https://devdocs.io) that docshelf has
downloaded. Lookups work offline; only the commands below use the network.

## Commands

- `python scripts/docshelf.py sources QUERY...` lists matching documentations
  (slug, name, release, download size; `(installed)` marks yours), shortest
  slug first, at most 30. Add `--refresh` to fetch the list again; it is
  otherwise cached for 24 hours.
- `install NAME...` downloads documentations. NAME is a slug (`python~3.14`), an
  alias (`py`), a family (`python`) or a title (`Node.js 24 LTS`). A family
  or alias picks the newest version, since DevDocs lists newest first; give
  the slug for another version. Prints `installed`, `updated` or
  `up to date`. A failed name does not stop the rest: each failure is
  printed and the exit code is the first failure's (5 when DevDocs answers
  404, i.e. no such documentation; 7 for other network errors). An
  unwritable cache (no permission, read-only or full disk) stops at the
  first name (exit 2) and lists the names not tried.
- `update [NAME...]` fetches the DevDocs list fresh (not the 24-hour copy)
  and re-downloads documentations whose DevDocs timestamp is newer; with
  no names, every installed docvol. One that DevDocs no longer lists is
  skipped with a warning.
- `remove NAME` deletes the downloaded docvol. Notes are kept.

A docset already on disk (Dash or Zeal) is used instead of `install`: the
documentation is not downloaded again. `install` of a documentation that
exists locally as a docset is skipped with a note (exit 0 if nothing else
failed) unless `--force`, which is for when the user explicitly asks for
the DevDocs copy. docshelf never installs, updates or removes docsets (see
[dash-zeal.md](dash-zeal.md)); `sources` also lists docsets Dash or Zeal
could download, when one of them is present.

## Suggesting docvols for a project

`python scripts/docshelf.py suggest` reads the project's build and version
files (`package.json`, `pyproject.toml`, `requirements*.txt`,
`CMakeLists.txt`, `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`,
`Dockerfile`, `Dockerfile.*`, `*.Dockerfile`, compose files, `.nvmrc` and
similar) in the scanned folder, its direct child folders and those of
`packages/` and `apps/`. The scanned folder is the one holding
`.docshelf.json` when that file is in or above the current folder within
the same git work tree; else the current folder. A note names it. It uses
no network: it matches the files against installed docvols and the cached
DevDocs list; versions in the files pick the matching docvol version. Each
line is `installed`, `docset` or `available`. It ends with a
`"docvols": [...]` list to paste into `.docshelf.json`; it never writes
that file. Searches naming an `available` entry exit 4 until it is
installed: after pasting, `install` with no NAME fetches them (check sizes
with `sources` first). A lower bound (`django>=3.2`) picks that
version's docs, since the code must also run on that minimum.

## Sizes

Some documentations are large (ansible is about 281 MB). Run `sources` first and
read the size column before installing a big one.

## Versions and aliases

Versions are separate docvols: `python~3.14` and `python~3.15`. Some
families have an unsuffixed slug for the current release (`node`) beside
numbered ones (`node~24_lts`). An alias such as `py` or `ng` names a whole
family (`py` is every `python~3.x`), not one docvol. `install py` gets the
newest release; `-d py` is ambiguous (exit 2, the slugs are listed) when two
releases are installed.

## Exit code 7: the network

Exit 7 means a download failed. The error names the host. Ask the user to
allow the hosts listed in `assets/allowlist.txt` (in this skill's folder):
`devdocs.io` and `documents.devdocs.io`. If an older list is cached,
`sources` and `install` use it and say so.

## Damaged docvol

A docvol whose index or page data cannot be read is skipped with a warning by
`search`, `types` and `fts` (exit 5 when it was named with `-d`, or when every
selected docvol is damaged). Repair a DevDocs docvol with
`docshelf.py remove NAME`, then `docshelf.py install NAME` (`remove` keeps
your notes; `install` alone says "up to date"). A Dash or Zeal docset is never
changed by docshelf: reinstall it in Dash or Zeal.

A docset that cannot be used because docshelf cannot write its cache copy
(exit 2; fix `DOCSHELF_CACHE_DIR` or free disk space) is skipped the same way.

## Built docvols

`list` shows docvols made by the `docshelf-build` skill (from a Sphinx
site's `objects.inv`) as `built`. They live in `<cache>/built/`; `install`
and `update` refuse them and say to rebuild with `docshelf-build`, and
`remove` deletes the docvol but keeps its build plan. A built docvol hides a
DevDocs one of the same name, with a warning.

## Where files go

Under the cache folder (`python scripts/docshelf.py where` prints it), in
`devdocs/<slug>/`. Set `DOCSHELF_CACHE_DIR` to use another folder. A failed
download leaves nothing half-written.

## Licences

`list` does not print licences. DevDocs' About page
(https://devdocs.io/about) has a table of every documentation with links
to its original sources and its copyright and licence. The same text is
in the `attribution` field per documentation in DevDocs' list
(`docs.json` in the cache). `show` and `fts` leave out the copy of it
that DevDocs puts at the end of every page.
Read one of them when you need to cite or redistribute a docvol.
