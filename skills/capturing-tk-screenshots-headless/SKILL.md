---
name: capturing-tk-screenshots-headless
description: Use when a Tkinter, Thonny, IDLE or other Tk/X11 desktop GUI must be run, seen or screenshotted in a headless Linux sandbox or CI with no monitor - "no display name and no $DISPLAY environment variable", black or overlapping captures, checking UI/editor themes, fonts, glyphs or emoji rendering, or showing a person what a widget looks like.
compatibility: Linux (or WSL) with Xvfb, xvfb-run and ImageMagick (import, convert), and a Python that has tkinter; scripts/grab_stable.py uses only ImageMagick.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Capturing Tk screenshots headless

## Overview
Run the GUI on a virtual X server (Xvfb) and capture with ImageMagick `import`. There is no window manager: no title bars, every window opens at 0,0, and `import -window <id>` copies whatever is on screen in that window's rectangle, including other windows covering it.

## Before you start
- Use a Python **that has tkinter**: `python -c "import tkinter"`. Sandbox system `python3` often lacks it; a venv with Thonny or `python3-tk` has it.
- Tools: `Xvfb`, `xvfb-run`, `import`, `convert` (ImageMagick). Often missing: `xdotool`, `xwininfo`, `scrot`. Don't plan on them.

## Recipe A: your own widget or test window
```bash
xvfb-run -a -s "-screen 0 1600x1200x24" PY capture.py
```
```python
import subprocess, tkinter as tk
root = tk.Tk(); root.withdraw()
wins = [make_window_1(root), make_window_2(root)]      # your Toplevels
for i, w in enumerate(wins, 1):
    for o in wins:                                       # show ONE window at a time
        o.deiconify() if o is w else o.withdraw()
    root.update(); root.after(300); root.update()        # let Tk finish drawing
    subprocess.run(["import", "-window", str(w.winfo_id()), f"win{i}.png"], check=True)
root.destroy()
```
Skip `mainloop()` in capture scripts; `update()` draws everything.

## Recipe B: a real application (Thonny, IDLE, ...)
1. `Xvfb :77 -screen 0 1200x800x24 &` (explicit display number, screen = desired image size).
2. Give the app a **throwaway config dir** with theme, font size and window geometry preset to fill the screen at 0,0 (most apps take a config-directory environment variable or option; check the app's docs). An empty config dir often opens a first-run or welcome dialog instead of the main window: preset the settings that skip it. Never touch the user's real config.
3. Open a file with real content so themes, syntax colors and fonts are visible.
4. Launch with `DISPLAY=:77 ... &`, then wait for it to settle instead of sleeping a guessed time:
   `python3 scripts/grab_stable.py :77 out.png` (waits until the screen is non-blank and stops changing, tolerates a blinking cursor; `--crop WxH+X+Y`, `--timeout`).
5. Kill the app, then Xvfb. Read the app's log for "Could not find ..." warnings.

## Always
- **Open every PNG yourself** (whatever image-viewing tool your harness has) before reporting, and describe what it actually shows: a capture that ran without errors can still be black, half-drawn or the wrong window.
- Keep scratch files out of the project; hand finished images to the person with your harness's file-sharing mechanism.
- Captures are 1:1 pixels at Tk's 1x rendering.
- Running in Claude Code? Also read `claude-code.md` for its tool names and container notes.

## Common mistakes
| Symptom | Cause / fix |
|---|---|
| Black or another window inside a capture | Windows overlap at 0,0: show one at a time, or place with `geometry("+X+Y")` and crop `-window root` |
| Capture of a half-built window | Missing `update()`/`after()`, or fixed sleep too short: use `grab_stable.py` |
| App ignored the theme | Wrong theme name or UI vs editor theme mixed up; check log |
| App at an offset on a black screen | Geometry not preset; screen size not matched |
| Emoji gray/outline, extra blank cell after ⬅️ | Tk 8.6 draws no color emoji; U+FE0F takes a cell. `fc-list ":charset=274c" family` shows which font supplies a glyph |
| `OSError: AF_UNIX path too long` at launch | The app's socket path (under a long config or runtime dir) exceeds the ~108-byte limit: use a shorter dir, or set `XDG_RUNTIME_DIR` to one |
| Fonts differ from the user's OS | Sandbox fonts (e.g. DejaVu) ≠ Windows Consolas/Segoe; say so |
