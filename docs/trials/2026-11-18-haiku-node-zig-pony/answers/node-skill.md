# Node.js 26.3.1 answers

Docs used: docshelf docvol `node` (Node.js 26.3.1), read offline via
`docshelf.py show` / `search`.

## N1. `path.basename('/foo/bar/baz/asdf/quux.html', '.html')`

**Answer:** `'quux'`

- Reference: `node:path#pathbasenamepath-suffix` (path.basename()). The doc
  example shows `path.basename('/foo/bar/baz/asdf/quux.html', '.html')`
  returns `'quux'`; without the suffix it returns `'quux.html'`.
- Confidence: high.

## N2. `node:sqlite` `new DatabaseSync(path, options)` defaults

**Answer:**
- `enableForeignKeyConstraints`: default `true`.
- `defensive`: default `true`.
- `defensive` became enabled by default in **v25.5.0 and v24.14.0** (the
  history table of the constructor says "Enable defensive by default" for
  those versions). The option itself was added in v25.1.0 and v24.12.0.
  Node 26 therefore has it on by default.

- Reference: `node:sqlite#new-databasesyncpath-options` (options list and
  History table). The `defensive` option also has `database.enableDefensive(active)`
  to change it at runtime.
- Confidence: high for both defaults and the version list (read from the
  constructor's History table). Medium only on whether the 25.5.0/24.14.0
  entry is the first version with the default-on behaviour, since the page
  states it in one history row only.

## N3. `process.permission.drop('fs.read', '/etc/myapp')` after `--permission --allow-fs-read=*`

**Answer:** No, that call will not revoke read access to just `/etc/myapp`
in this setup. The grant was a wildcard, and the docs say individual paths
under a wildcard grant cannot be dropped: "If a permission was granted
using a wildcard (*), such as --allow-fs-read=*, individual paths cannot be
dropped - only the entire scope can be dropped (by calling drop() without a
reference)."

What it can do instead: `process.permission.drop('fs.read')` (no reference)
drops the whole `fs.read` scope, so all file system read access is revoked,
irreversibly. Other options are to start the process with narrower grants
(for example `--allow-fs-read=<dir>` for each needed directory, instead of
`*`), where a granted directory can be dropped by passing that same
directory to `drop()`.

Note: the docs contradict themselves here. The `process` page's example
calls `drop('fs.read', '/etc/myapp')` after a wildcard grant, and shows the
"will now throw ERR_ACCESS_DENIED" result, but the same page's rule and the
`permission` page's rule both say this is not allowed under a wildcard. I
went with the explicit rule. Confidence on the "no" answer: medium-high.
Confidence that the whole-scope drop is the only alternative for a wildcard
grant: high.

`process.permission.drop()` was added in **v26.3.0** (`Added in: v26.3.0`).
Reference: `node:process#processpermissiondropscope-reference` and
`node:permissions#permissiondropscope-reference`. Confidence: high.
