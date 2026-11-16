# Getting docsets

Read this before `sources` or `remove`, when a needed docset is missing,
or when `sources` fails.

- The script downloads no docsets and never contacts kapeli.com, where
  every docset archive is served (Kapeli asked tools not to add load to his
  servers). Docsets come from Dash or Zeal, which download them for the
  user.
- A missing docset: ask the user to download it in Dash (Settings >
  Downloads) or Zeal (Tools > Docsets > Available). If the store doesn't
  read that app's folder yet, add it with `where --set STORE --read-from
  DIR` ([setup.md](setup.md)); `where --discover` finds the folder.
- On a machine without Dash or Zeal (a sandbox, CI), the user can copy a
  `.docset` folder from their own computer into the store: the script
  reads it like any other. Delete it by hand when done (`remove` refuses
  docsets the script didn't install).
- To tell the user what Dash or Zeal can download: `sources QUERY`
  searches the names of official and user-contributed docsets (Zeal's
  catalog adds titles and versions when it is the source), labels each,
  and says which are already here. Cheat sheets aren't listed; browse them
  in Dash or Zeal. The lists are cached for a week; `sources --refresh`
  re-checks them. A "note (no action needed)" on stderr says a list came
  from Zeal's catalog because GitHub was unreachable; it is complete.
  Exit 7 with results means one list is missing (the output says which).
- If the network only reaches allowed hosts (a sandbox, a corporate proxy, a
  cloud agent environment) and `sources` fails (exit 7), give the user
  [../assets/allowlist.txt](../assets/allowlist.txt): the hosts to allow.
- Cheat sheets are short (Git's has 81 entries); prefer a full docset when
  one exists.
- A docset's name for `-d` and REFs is the one `list` prints, which can
  differ from the name the app shows (Arm Morello A64 ISA is
  `arm64morello`).
- Manage: `list` shows the docsets found and their versions. Update
  docsets in Dash or Zeal. `remove NAME` deletes a docset that an earlier
  version of this script installed (notes are kept).
- `fts` builds a docset's text index on first use (seconds for large
  docsets); `index-text NAME` builds it ahead of time.
