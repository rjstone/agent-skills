# docshelf-build 0.5.0: Doxygen real-site trials (2026-11-23)

The gate for merging the `doxygen` type (the user, 2026-11-23): both sites
must build and pass spot-checks. Run in a Claude Code cloud session with a
throwaway `DOCSHELF_CACHE_DIR`; docshelf from this repo for the lookups.

## GLFW, `https://www.glfw.org/docs/latest/` (search index)

- `detect`: `type: doxygen`, `index: search` (Doxygen 1.9.8).
- First build (b44d50e): 13 full, 24 stub, 309 entries, 31 s. Two faults:
  - Macro 41: the key, hint and error macros (`GLFW_KEY_*`, 295 in all)
    are listed only in `search/all_*.js`, so `group__keys` and others had
    only their heading entry and became stubs. Fixed in 08f6fef: entries
    from `all` with an anchor, on a non-prose page, not already typed
    (ALL_CAPS as Macro, others as Symbol).
  - Stub titles such as "guide": the pages index also lists title
    keywords whose third field is the full title. Fixed in the next
    commit: the full title is used.
- Final: 37 pages, 22 full, 15 stub, 0 failed; Macro 336, Function 151,
  Type 33, Variable 19, Module 16, Page 14, Struct 5, File 2.
- Spot-checks: `glfwCreateWindow` (Function, `show` lands on the member
  with its signature and links to `GLFWwindow`/`GLFWmonitor`),
  `GLFWwindow` (Type), `GLFW_KEY_ESCAPE` (Macro), `window_guide` a stub
  titled "Window guide". Pass.

## wxWidgets, `https://docs.wxwidgets.org/3.2/` (menu path)

- `detect`: `type: doxygen`, `index: menu` (Doxygen 1.9.1; server-side
  search, no `search/*.js`).
- Plan: 192 index pages read; 1,644 pages, 1,268 full, 376 stub; 24,174
  entries: Function 13,959, Constant 3,830, Macro 3,118, Variable 1,166,
  Class 1,007, File 547, Enum 300, Type 99, Module 69, Struct 18, Page 3.
- Build: 1,268 pages fetched, 0 failed, 16 min 42 s at the polite rate.
- Found: the site sits behind Cloudflare, whose per-response id made the
  raw-file hash differ on every read ("inventory changed" on each build),
  and `build SOURCE` read the 192 index pages twice. Fixed in de56f53: the
  hash covers the entries, and `build SOURCE` reuses its plan's read.
- Spot-checks: `wxWindow::SetSize` (Function, `show` lands on overload
  1/4 with signature), `wxGetApp` (global Function), `wxASSERT` (Macro),
  `wxID_OK` (Constant). Pass. `wxUSE_UNICODE` is not found because the
  site's own macro index does not list it (0 on `globals_defs_u.html`).

## Result

Both sites pass. Not tried: Arm CMSIS components (optional in the spec).
