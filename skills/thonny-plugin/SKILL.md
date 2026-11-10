---
name: thonny-plugin
description: Use when writing, installing, testing or debugging a plugin for the Thonny Python IDE (thonnycontrib namespace, load_plugin, workbench, editor, runner or debugger APIs), or when a Thonny plugin "does nothing" after install.
compatibility: For the Thonny IDE; the API reference was verified against Thonny 5.0.1.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Thonny plugin authoring

Thonny discovers 3rd-party plugins at startup: any module or package under
the `thonnycontrib` namespace exposing a parameterless `load_plugin()`,
which Thonny calls exactly once. Everything else is convention around that.

## Layout

```text
thonnycontrib/
    __init__.py          # empty (namespace marker; a regular package works,
                         # but then this directory shadows namespace installs
                         # anywhere earlier on sys.path)
    my_plugin/
        __init__.py      # defines load_plugin()
```

`load_plugin()` registers with the workbench — typically
`get_workbench().add_command(...)` and/or `get_workbench().add_view(...)`.
Keep a module-level reference to anything that must outlive the call
(servers, threads); Thonny keeps only what you bind or thread yourself.

## Install location (the failure that matters)

Thonny's interpreter runs **isolated** (`no_user_site=1`,
`ignore_environment=1`, `isolated=1` — confirm with
`<thonny python> -c "import sys; print(sys.flags)"`). Its plugin loader
only looks in Thonny's own plugin folder:

- `<Thonny user data folder>/plugins/` plus the user-site layout of
  Thonny's Python: `PythonXY\site-packages` on Windows,
  `lib/pythonX.Y/site-packages` on Linux, `lib/python/site-packages` for a
  macOS framework Python. Put `thonnycontrib/` inside that.
- The user data folder: `%APPDATA%\Thonny` (Windows), `~/Library/Thonny`
  (macOS), `$XDG_CONFIG_HOME/Thonny` or `~/.config/Thonny` (Linux);
  `user_data` beside the program for a portable Thonny; `THONNY_USER_DIR`
  overrides all of them. Tools > "Open Thonny data folder..." opens it.
- Example (Windows, Thonny 5.0.1 with Python 3.14):
  `%APPDATA%\Thonny\plugins\Python314\site-packages\thonnycontrib\`
- **NOT** the interpreter's user-site (e.g.
  `%APPDATA%\Python\Python314\site-packages`): it is not on Thonny's path,
  so a plugin installed there silently never loads — no error, no menu
  item, nothing in the log.
- After copying, strip `__pycache__` and **restart Thonny** (full quit;
  the new process is what loads it). Verify with the menu item, not the
  import.

## UI-thread rule

HTTP threads, background threads, and timers must never touch Tk or
Thonny objects directly. Marshal with `get_workbench().after(0, fn)` and
block the worker on a `queue.Queue` for the result (10 s timeout is plenty).
Read-only Tk getters also count — call them on the UI thread.

## Test ladder (each step proves strictly more)

1. **Syntax/import** with Thonny's bundled interpreter (Windows:
   `%LOCALAPPDATA%\Programs\Thonny\python.exe`; never a bare `python`,
   which on Windows may be the Microsoft Store stub). Proves the file
   parses and `load_plugin` exists. Proves nothing about loading. Running
   the file directly (`python.exe plugin.py`) proves even less — it never
   calls `load_plugin`.
2. **Restart Thonny, check the Tools menu** (or view) for your item. Absent
   item = wrong install location (see above) or an exception at load —
   the latter IS logged (`frontend.log` in the user data folder; look for
   "Failed loading plugin"). No log error + no item = location problem.
3. **Exercise it live** against the running Thonny (click it; or call its
   HTTP endpoint if it serves one). Import checks cannot replace this.

## API reference

Verified against Thonny 5.0.1 — do not trust memory or newer upstream;
signatures drift (e.g. `get_current_breakpoints()` keys by
`get_filename()` in 5.0.1). Re-verify anything not listed with
`inspect.signature`/`inspect.getsource` against the installed `thonny`
package (Windows: `%LOCALAPPDATA%\Programs\Thonny\Lib\site-packages\thonny\`).
Full table: [references/api-5.0.1.md](references/api-5.0.1.md).

## Gotchas

- Thonny runs the file **on disk**, not the editor buffer — a "run this"
  feature must save first (`save_all_named_editors()`), or it executes
  stale code.
- `WorkbenchClose` fires **only** on window close (`workbench.py:_on_close`
  is its sole `event_generate`). Cleanup bound to it never runs otherwise;
  files your plugin writes are never auto-removed while Thonny lives.
- **Two localhost listeners on one Thonny pid is normal.** Thonny's own
  single-instance IPC server binds `127.0.0.1:0` (`_create_server_socket`).
  It accepts-then-hangs on HTTP and logs `ast.literal_eval` errors for
  `GET /ping` in `frontend.log`. Don't mistake it for your server, and
  don't probe unknown localhost ports with HTTP unless you accept log spam.
- Windows liveness: `os.kill(pid, 0)` raises `WinError 87` even for **live**
  GUI processes of the same user — it cannot distinguish them from dead
  PIDs. Probe with `ctypes` `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`:
  non-NULL handle (or access-denied) = alive, NULL + error 87 = dead.
- Breakpoints mirror gutter clicks: `tag_add("breakpoint_line", ...)` on the
  code view text + `update_gutter()`; skip blank/`#` lines; read back with
  `editors.get_current_breakpoints()`.
