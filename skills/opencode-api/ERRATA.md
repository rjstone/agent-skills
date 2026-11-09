# Errata: mistakes in the cached opencode OpenAPI spec

`references/openapi.json` is overwritten by `scripts/refresh_references.py`;
corrections live here instead. When a refresh changes the spec, the script
prints `re-check errata: <ids>`: re-verify each, then update or delete it.

Entry format (the script reads the `## E..` heading):

```
## E01: <short title>
- Operation: `session.prompt` (POST /api/session/{sessionID}/prompt)
- Spec says: <claim>
- Actually: <what the server does>
- Evidence: <request and response, or source commit>
- Checked: <YYYY-MM-DD> against opencode <version> (`GET /api/info`)
```

No entries yet.
