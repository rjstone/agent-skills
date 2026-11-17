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

- `DOCSHELF_DOCSET_DIRS`: extra folders (separated like `PATH`), first.
- Zeal on Linux: `$XDG_DATA_HOME/Zeal/Zeal/docsets`, by default
  `~/.local/share/Zeal/Zeal/docsets`; Flatpak:
  `~/.var/app/org.zealdocs.Zeal/data/Zeal/Zeal/docsets`.
- Zeal on macOS: `~/Library/Application Support/Zeal/Zeal/docsets`.
- Zeal on Windows: `%LOCALAPPDATA%\Zeal\Zeal\docsets`.
- A custom folder set in Zeal's settings (`Zeal.conf`, the macOS plist or the
  Windows registry), and for portable Zeal the `docsets` folder beside the
  program (or the path in its `zeal.ini`).
- Dash on macOS: `~/Library/Application Support/Dash/DocSets`.
- Dash for Windows (Microsoft Store app): somewhere under
  `%LOCALAPPDATA%\Packages\<Kapeli Dash package>\`. The exact folder is
  unverified; set `DOCSHELF_DOCSET_DIRS` if it isn't found.

## REFs

- `<Name>:<id>`: an index entry (what `search` prints).
- `<Name>:page:<path>[#anchor]`: a page of the docset.

`-d` takes a docset's name or a family name (all versions, with a note).

## Read-only

docshelf opens a docset's index read-only and never writes into a docset
folder; its own indexes and notes live in the cache and notes folders.
Docsets with a WAL index work: SQLite may use the docset's existing `-shm`
coordination file, as Dash and Zeal do.

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
