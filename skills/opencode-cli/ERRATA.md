# Errata: mistakes in the cached opencode CLI docs

`references/` is overwritten by `scripts/refresh_references.py`; corrections
live here instead. When a refresh changes a page with entries, the script
prints `re-check errata: <ids>`: re-verify each, then update or delete it.

Entry format (the script reads the `## E..` heading and the `- Page:` line):

```
## E01: <short title>
- Page: `commands.md` (section "<heading>")
- Docs say: <claim>
- Actually: <what is true>
- Evidence: <`--help` output, real behavior, or commit>
- Checked: <YYYY-MM-DD> against opencode <version> (`opencode --version`)
```

No entries yet.
