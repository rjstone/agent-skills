# Claude Code notes

Only the harness-specific parts; the method is in `SKILL.md`.

## Tools
- **View a capture:** the `Read` tool displays PNG files as images. Read every capture before
  describing it.
- **Give a capture to the person:** `SendUserFile` with `display: "render"` for images they
  should look at now, `"attach"` for files to download. In a cloud session the person can only
  open files inside the working directory or the scratchpad, so send them rather than citing paths.
- **Scratch files:** use the session's scratchpad directory (named in the system prompt), not the
  repository and not `/tmp`, unless told otherwise.

## Claude Code on the web (cloud container), observed
- `Xvfb`, `xvfb-run`, `import` and `convert` are preinstalled; `xdotool`, `xwininfo`, `scrot`
  are not.
- The system `python3` has no tkinter. Create a venv from a Python that has it, or use a venv
  where Thonny is installed (`pip install thonny`).
- Fonts include DejaVu, Liberation, JetBrains Mono, Noto Color Emoji (Tk 8.6 cannot draw it in
  color); no Windows fonts such as Consolas or Segoe UI.
- Captures sent to a phone or tablet are viewed scaled; Tk renders at 1x, so prefer larger
  window content over tiny screenshots.
