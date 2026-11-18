# Node.js 26.3.1 answers

## N1. path.basename('/foo/bar/baz/asdf/quux.html', '.html')

**Answer:** `'quux'`

The suffix argument is removed from the end of the last path segment. Without the suffix, the same call returns `'quux.html'`.

- URL: https://nodejs.org/docs/v26.3.1/api/path.html
- Confidence: high (the v26.3.1 docs page shows both examples with these return values)

## N2. node:sqlite DatabaseSync defaults

**Answer:**
- `enableForeignKeyConstraints` defaults to `true`.
- `defensive` defaults to `true`.
- `defensive` became enabled by default in v25.5.0 and v24.14.0 (changelog entry: "Enable `defensive` by default."). The option itself was added in v25.1.0 and v24.12.0.

- URL: https://nodejs.org/docs/v26.3.1/api/sqlite.html
- Confidence: medium-high (defaults and changelog are read from the v26.3.1 docs page; the page was read through a summarizing fetch, so the exact changelog wording was not checked against the raw HTML)

## N3. process.permission.drop('fs.read', '/etc/myapp') under --allow-fs-read=*

**Answer:** No. A `*` grant can only be dropped as a whole scope, not per path. The call `process.permission.drop('fs.read', '/etc/myapp')` does not revoke that directory.

What the process can do instead:
- Drop all read access: `process.permission.drop('fs.read')`. This is irreversible, and it is the only way to remove read access under a wildcard grant.
- Or restart with a narrower grant (for example, listing the specific directories instead of `*`), so that a later per-directory drop is possible.

Other points from the docs: dropping only affects future checks, and already-open file descriptors, sockets, child processes and workers stay open. The docs' example comment says the later read "will now throw ERR_ACCESS_DENIED", but that example calls `process.permission.has()`, which returns a boolean. Treat the example comment as unverified.

`process.permission.drop()` was added in **v26.3.0** (the page's "Added in: v26.3.0" line).

- URLs:
  - https://nodejs.org/docs/v26.3.1/api/process.html (the `process.permission.drop` section, read at an offset past the first 100,000 characters)
  - https://nodejs.org/docs/v26.3.1/api/permissions.html
  - https://nodejs.org/download/nightly/v27.0.0-nightly202609082987a5965f/docs/api/permissions.html (search result only; not read)
- Confidence: medium-high on the behavior (the page states the wildcard rule directly). Medium on the version: the "Added in: v26.3.0" line came from one read, and a separate summarizing read of the permissions page did not find a version. A third-party blog also points to 26.3.0. Check the History section on nodejs.org before relying on the version.
