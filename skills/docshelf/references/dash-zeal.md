# Dash and Zeal docsets

docshelf reads docsets that Dash or Zeal already put on disk, read-only, and
treats each as a docvol: `list`, `search`, `show`, `fts`, `notes` and `where`
work as for DevDocs. It never downloads, updates or removes a docset.

## Check for another server first

If an MCP server that reads docsets is configured and works, prefer it:

- Kapeli's Dash MCP server (https://github.com/Kapeli/dash-mcp-server;
  macOS, talks to the running Dash app).
- Small third-party servers that read Zeal's folder, for example
  https://github.com/andreas-mausch/docset-mcp and
  https://github.com/keturn/ZDocsetMCP.

## Where docshelf looks

`where` prints the folders found and the Dash/Zeal apps detected. Folders,
searched in this order (the first docset of a name wins):

1. `DOCSHELF_DOCSET_DIRS`: extra folders (separated like `PATH`).
2. dasht: `DASHT_DOCSETS_DIR`, then `$XDG_DATA_HOME/dasht/docsets` (by
   default `~/.local/share/dasht/docsets`).
3. A custom folder set in Zeal's settings: `Zeal.conf` (in
   `$XDG_CONFIG_HOME/Zeal/`, then Flatpak's
   `~/.var/app/org.zealdocs.Zeal/config/Zeal/`), the macOS plist, the
   Windows registry, and for portable Zeal the `docsets` folder beside the
   program (or the path in its `zeal.ini`).
4. Zeal on Linux: `$XDG_DATA_HOME/Zeal/Zeal/docsets`, then
   `~/.local/share/Zeal/Zeal/docsets`, then Flatpak's
   `~/.var/app/org.zealdocs.Zeal/data/Zeal/Zeal/docsets`.
5. Zeal on macOS: `~/Library/Application Support/Zeal/Zeal/docsets`.
6. Zeal on Windows: `%LOCALAPPDATA%\Zeal\Zeal\docsets`.
7. Dash on macOS: `~/Library/Application Support/Dash/DocSets`.
8. Dash for Windows (Microsoft Store app): somewhere under
   `%LOCALAPPDATA%\Packages\<Kapeli Dash package>\`. The exact folder is
   unverified; set `DOCSHELF_DOCSET_DIRS` if it isn't found.

## REFs

- `<Name>:<id>`: an index entry (what `search` prints).
- `<Name>:page:<path>[#anchor]`: a page of the docset.

`-d` takes a docset's name or a family name (all versions, with a note).

## Read-only

docshelf never writes into a docset folder: it opens a docset's index
read-only, and reads a WAL-mode index (one with a `docSet.dsidx-wal` file)
from a copy in its cache, refreshed when the docset changes. Its own indexes
and notes live in the cache and notes folders.

A header or footer that most pages of a docset repeat exactly (navigation
such as "Skip to main content", a copyright line) is shown once, on one page
(the docset's index page, else the first entry's page), and left out of
`show`, `fts` and headings everywhere else.

## When the docset isn't on disk

`sources QUERY` lists docsets Dash or Zeal could download (a network lookup,
only when Dash or Zeal is present or a docset folder exists). If one fits
and Dash or Zeal looks installed, tell the user, in substance:

> It looks like you have <Dash/Zeal> installed and there's a docset called
> '...' for this, but I can't install it. If you install it, I can use it.
> Otherwise I'll download <the DevDocs alternative>.

Then ask how to proceed. Don't install anything first.

## Redundant copies and `install --force`

`install` refuses a documentation that exists locally as a docset. Pass
`--force` only when the user explicitly asks for the DevDocs copy. `list`
flags a DevDocs docvol and a docset of the same documentation as "also as";
ask the user whether to remove the DevDocs copy (`remove`). Never remove a
docset: Dash or Zeal manages it.

## Terms

Kapeli's docsets are for personal use or with Dash or Zeal; other uses need
Kapeli's permission (see the README of https://github.com/Kapeli/feeds).
User-contributed docsets carry their own licences.
