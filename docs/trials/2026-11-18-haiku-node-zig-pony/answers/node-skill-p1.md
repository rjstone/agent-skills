# Node.js 26.3.1 answers (docshelf, offline DevDocs "node" docvol)

## N1. path.basename('/foo/bar/baz/asdf/quux.html', '.html')

**Answer:** `'quux'`

The suffix is removed from the end of the last path portion. Without the suffix argument the result would be `'quux.html'`.

**Reference:** `node:path#pathbasenamepath-suffix` (path.basename(path[, suffix]); the doc example shows `path.basename('/foo/bar/baz/asdf/quux.html', '.html')` returns `'quux'`).

**Confidence:** high

## N2. node:sqlite DatabaseSync options

**Answer:**
- `enableForeignKeyConstraints`: default **true**.
- `defensive`: default **true**.
- `defensive` became enabled by default in **v25.5.0** and **v24.14.0** (doc history: "v25.5.0, v24.14.0 | Enable defensive by default.").
- Background: the `defensive` option was added in v25.1.0 and v24.12.0 (history: "Add defensive option."). Before the v25.5.0/v24.14.0 change it was not on by default; the doc does not state its earlier default value, so I did not state it.

**Reference:** `node:sqlite#new-databasesyncpath-options` (options list with the defaults; History table).

**Confidence:** high for the defaults and the v25.5.0 / v24.14.0 change. Medium for the claim that the default was previously off, since the docs state only the version change, not the prior value.

## N3. process.permission.drop with --permission --allow-fs-read=*

**Answer:** No. The process cannot call `process.permission.drop('fs.read', '/etc/myapp')` to revoke read access to only that directory. The reference passed to `drop()` must match the original grant. When the grant is a wildcard (`--allow-fs-read=*`), individual paths cannot be dropped; only the whole scope can be dropped, by calling `process.permission.drop('fs.read')` with no reference. That revokes all file system read permission, and the drop is irreversible.

What it can do instead:
- Drop the entire `fs.read` scope after startup has finished reading what it needs (`process.permission.drop('fs.read')`). This is all-or-nothing.
- Restart the process with narrower grants (for example `--allow-fs-read=<specific paths>` instead of `*`). Then `drop('fs.read', '<exact granted directory>')` works for that exact grant. Dropping a directory granted as `/my/folder` does not allow dropping individual files inside it.
- Enforce the restriction in application code (a wrapper around `fs` calls that refuses paths under `/etc/myapp`). This is not a Node permission check.

Note: dropping a permission only affects future checks and does not close resources that are already open.

**Version:** `process.permission.drop()` was added in **v26.3.0** (per the `process.permission.drop(scope[, reference])` section, "Added in: v26.3.0").

**Reference:** `node:process#processpermissiondropscope-reference` and `node:permissions#permissiondropscope-reference` (the wildcard rule and the directory rule).

**Confidence:** high for the no-answer, the wildcard rule, and the v26.3.0 version. Medium for the "restart with narrower grants" alternative, which follows from the docs' rules but is not written there as a recommendation.
