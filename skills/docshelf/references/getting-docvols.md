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
  `up to date`.
- `update [NAME...]` fetches the DevDocs list fresh (not the 24-hour copy)
  and re-downloads documentations whose DevDocs timestamp is newer; with
  no names, every installed docvol. One that DevDocs no longer lists is
  skipped with a warning.
- `remove NAME` deletes the downloaded docvol. Notes are kept.

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
