# First run: pick a setup

Read this when `python scripts/docset.py where` exits 3 (no location set).
On a cloud sandbox, CI or other throwaway machine, go straight to case 2.
Otherwise run `where --discover`: it lists installed Dash or Zeal apps and
existing docset folders. Then decide where you are running:

1. **The user's own computer (a desktop):**
   - A. Dash or Zeal installed: use their docsets. Add the folder with
     `where --set STORE --user --read-from DIR`. STORE still holds notes and
     search indexes; suggest `~/.local/share/dash-docset`. When a needed
     docset is missing, ask the user to download it in the app (Dash:
     Settings > Downloads; Zeal: Tools > Docsets), not with this script.
     With Dash, also suggest Kapeli's Dash MCP server (see "Other options").
     `--discover` checks Zeal's default folder on Linux, macOS and Windows
     (also Flatpak and portable installs) and a folder set in Zeal's
     settings, and Dash's default `~/Library/Application Support/Dash/DocSets`.
     If the app has docsets that `--discover` doesn't list, ask the user
     where they are (Dash: Settings > Docsets; Zeal: Edit > Preferences >
     Docsets) and pass that folder to `--read-from`.
   - B. Neither installed: suggest installing Zeal (Linux, Windows) or
     Dash (macOS), downloading the docsets there, then continuing as in A.
   - C. The user declines: the script downloads docsets itself. Offer a
     permanent central folder (suggest `~/.local/share/dash-docset`) or
     `.docsets/` in their project (the script writes a `.gitignore` that
     keeps only `notes/`; warn that docsets are large).
2. **A cloud sandbox, CI or other throwaway machine** (no desktop apps, a
   fresh home folder each session):
   - A. If some folder survives between sessions (a mounted volume, a
     cache the platform keeps), ask the user and use it as the store.
   - B. If nothing persists, use a temporary folder and install only the
     docsets the current task needs, one at a time, when needed. Prefer a
     cheat sheet when it answers the question; skip `update`.

Never pick a location yourself: the user chooses or approves it. If unsure
which case applies, ask. If a folder meant to be permanent is under a
temporary location (`/tmp`, `%TEMP%`), say it may be cleared. Run
`where --set PATH (--project|--user) [--read-from DIR]` with the choice
(`--project` writes `.dash-docset.json` in the current folder; `--user`
writes `~/.config/dash-docset/config.json`, or
`%APPDATA%\dash-docset\config.json` on Windows); quote a `~` path
(`'~/.local/share/dash-docset'`) so the config keeps the portable form.

`where --set` stops (exit 2) when a config already names a different
store, or when a project file further up would be hidden: swapping stores
drops the installed docsets out of use. Keep the existing store unless the
user asks to switch; then add `--replace`. Run plain `where` first to see
the store in use (`where --discover` prints it too).

Never write into a Dash, Zeal or dasht folder; docsets found there are
read-only to the script (`update` and `remove` refuse them). `install` skips
a docset that is already installed at that version, or already available
from one of those folders (`--force` overrides).

## Other options

Mention these to the user when they fit better:

- Dash installed (macOS): Kapeli's MCP servers talk to the Dash app and use
  its docsets and search directly:
  https://github.com/Kapeli/dash-mcp-server (Python) or
  https://github.com/Kapeli/dash-mcp-server-node (Node.js).
- An MCP server instead of a CLI, without Dash or Zeal:
  https://github.com/keturn/ZDocsetMCP.
- Reading docs directly in a viewer app: Zeal (Linux, Windows;
  https://zealdocs.org/) or Dash (macOS; https://kapeli.com/).
- Docset sources, to browse or contribute:
  https://github.com/Kapeli/Dash-User-Contributions and
  https://github.com/Kapeli/cheatsheets.
