# Thonny 5.0.1 plugin API (verified)

Source of truth: the installed `thonny` package (Windows:
`%LOCALAPPDATA%\Programs\Thonny\Lib\site-packages\thonny\`). Checked
against 5.0.1; re-verify with `inspect` before trusting anything else,
including newer upstream checkouts.

Conventions: `from thonny import get_workbench, get_runner, get_shell`;
UI-thread rule applies to
every Tk/Thonny touch (see SKILL.md).

## Workbench (`thonny/workbench.py`)

| Call | Notes |
|---|---|
| `get_workbench().add_command(command_id, menu_name, command_label, handler, ...)` | `menu_name="tools"` for Tools menu. Called once per plugin load. |
| `get_workbench().add_view(...)` | Adds a dockable pane (Variables/Files style). |
| `get_workbench().get_editor_notebook()` | Returns the `EditorNotebook`. |
| `get_workbench().bind("WorkbenchClose", fn, True)` | Custom (non-`<...`>`) event; fires only on window close. Same convention as built-in `files.py`, `event_logging.py`. |
| `get_workbench().title()` | Main window title (UI thread). |
| `get_workbench().after(0, fn)` | Marshal work to the UI thread. |

## Editor notebook (`thonny/editors.py`)

| Call | Notes |
|---|---|
| `notebook.get_all_editors()` | All open editors. |
| `notebook.get_current_editor()` / `get_current_editor_content()` | `None` when nothing open. |
| `notebook.show_file(path)` / `show_file_at_line(path, line)` | Opens (or focuses) a file. |
| `notebook.open_new_file()` | Untitled editor. |
| `notebook.save_all_named_editors()` | Save before run/debug. |
| `editors.get_current_breakpoints()` | `{filename: [lines]}`; 5.0.1 keys by `editor.get_filename()`. |
| `editor.get_filename()` / `editor.is_modified()` | |
| `editor.get_code_view()` → `.text` | Tk `Text` widget; `tag_add("sel", start, end)` + `see(start)` to highlight; `get("1.0", "end-1c")` reads text. |
| `editor.get_code_view().get_breakpoint_line_numbers()` | Lines carrying the `"breakpoint_line"` tag. |
| `editor.get_code_view().update_gutter(clean=True)` | Refresh after programmatic breakpoint changes. |

## Runner and shell (`thonny/running.py`; getters in `thonny/__init__.py`)

| Call | Notes |
|---|---|
| `get_runner()` | The `Runner`. |
| `runner.cmd_run_current_script()` | Run (saves? no — save first yourself). |
| `runner.cmd_stop_restart()` | Stops run AND debug sessions. |
| `runner.execute_current("Debug")` / `("FastDebug")` | Start debugger (nicer/faster). Entry via `thonny.plugins.debugger` helpers; import inside the UI function so the plugin survives without the debugger plugin. |
| `runner.is_running()` / `runner.get_state()` | `get_state()`: `"waiting_toplevel_command"` (idle), `"waiting_debugger_command"` (paused), `"running"`. |
| `runner.is_waiting_debugger_command()` | Gate for step commands. |
| `runner.send_program_input(text)` | Feed a waiting `input()`. |
| `get_shell()` | `ShellView`; read `.text.get("1.0", "end-1c")` on the UI thread. |

## Debugger (`thonny/plugins/debugger.py`)

Step commands go through the debugger module, not the runner:

```python
import thonny.plugins.debugger as dbg  # inside the UI function, not module top
dbg._issue_debugger_command("step_over")  # step_over | step_into | step_out | resume | step_back
```

- Guard with `runner.is_waiting_debugger_command()`; without it the call raises.
- `step_back` additionally needs the nicer tracer (`is_waiting` + tracer check inside `command_enabled`).
- No `run_to_cursor` without cursor plumbing: it needs a `focus`/`frame_id` context that code outside the debugger UI doesn't have.
- Breakpoints set while paused take effect on the next step command (re-read per command via `get_effective_breakpoints`).

## Minimal example (Tools command reading the editor)

```python
"""Thonny plugin: Tools -> greeting with the current file name."""

from thonny import get_workbench
from tkinter.messagebox import showinfo


def _greet():
    editor = get_workbench().get_editor_notebook().get_current_editor()
    name = editor.get_filename() if editor else None
    showinfo("Plugin", f"Current file: {name}")


def load_plugin():
    get_workbench().add_command(
        command_id="my_greet",
        menu_name="tools",
        command_label="Greet file",
        handler=_greet,
    )
```

Install: copy the `thonnycontrib` package into Thonny's plugin folder (see
SKILL.md, "Install location"; e.g. Windows
`%APPDATA%\Thonny\plugins\Python314\site-packages\`), delete
`__pycache__`, restart Thonny, look for Tools → "Greet file".
