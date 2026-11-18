# Node.js 26.3.1 answers (p2)

## N1. path.basename('/foo/bar/baz/asdf/quux.html', '.html')

**Answer:** `'quux'`

**Reference:** DevDocs `node:path#pathbasenamepath-suffix` (path.basename(path[, suffix])). The page's example is `path.basename('/foo/bar/baz/asdf/quux.html', '.html'); // Returns: 'quux'`.

**Confidence:** high

## N2. node:sqlite DatabaseSync defaults

- `enableForeignKeyConstraints`: default **true**.
- `defensive`: default **true**.

`defensive` became on by default in **v25.5.0 and v24.14.0** ("Enable defensive by default"). The option itself was added in **v25.1.0 and v24.12.0** ("Add defensive option"). The page's history table lists no change to the default for v22.x.

**Reference:** DevDocs `node:sqlite#new-databasesyncpath-options` (new DatabaseSync(path[, options]), options list and Changes table).

**Confidence:** high for the two defaults and the 25.5.0 / 24.14.0 change. Medium-high on "not in v22": the doc table shows no v22 change, but I did not check a changelog to confirm that.

## N3. process.permission.drop with --allow-fs-read=*

**Answer:** No. With `--allow-fs-read=*` the grant is a wildcard, and the docs say that "individual paths cannot be dropped - only the entire scope can be dropped (by calling drop() without a reference)". So `process.permission.drop('fs.read', '/etc/myapp')` will not revoke read access to that directory alone.

What it can do instead:
- Call `process.permission.drop('fs.read')` with no reference. This drops ALL file system read permissions for the process, and the drop is irreversible.
- Restart the process with narrower grants instead of `*` (for example, list the allowed directories explicitly with `--allow-fs-read=...`). Directory grants can be dropped as whole directories, and the other grants stay in force.
- Read what is needed at startup, then drop the whole `fs.read` scope if no later reads are needed.

Note: dropping a permission only affects future access checks. It does not close file descriptors that are already open.

**Version:** `process.permission.drop()` was added in **v26.3.0** (`Added in: v26.3.0`, status Stability 1.1).

**Reference:** DevDocs `node:process#processpermissiondropscope-reference` (process.permission.drop), and `node:permissions#permissiondropscope-reference` (same rules, from the Permissions page).

**Confidence:** high for the wildcard rule, the whole-scope drop, and v26.3.0. Medium for the "restart with narrower grants" suggestion, which is my inference from the docs rule that a directory grant can be dropped as a whole, not a documented recommendation.
