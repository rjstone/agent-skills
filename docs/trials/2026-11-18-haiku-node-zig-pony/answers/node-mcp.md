# Node.js 26.3.1 questions (answered from docshelf, node docvol)

## N1 (easy)

Question: What does `path.basename('/foo/bar/baz/asdf/quux.html', '.html')` return?

Answer: `'quux'`. The suffix is removed from the last path portion. Without the suffix argument the result would be `'quux.html'`.

REF: `node:path#pathbasenamepath-suffix`

Confidence: high

## N2 (medium)

Question: In `node:sqlite`, what are the default values of `enableForeignKeyConstraints` and `defensive` in `new DatabaseSync(path, options)`, and in which Node.js versions did `defensive` become enabled by default?

Answer:
- `enableForeignKeyConstraints`: default `true`. Foreign key constraints are enforced unless set to `false`. It can be toggled later with `PRAGMA foreign_keys`.
- `defensive`: default `true`. When enabled, SQL features that let ordinary SQL deliberately corrupt the database file are disabled. It can also be set with `enableDefensive()`.
- `defensive` became enabled by default in v25.5.0 and v24.14.0. The option itself was added in v25.1.0 and v24.12.0.

REF: `node:sqlite#new-databasesyncpath-options`

Confidence: high

## N3 (hard)

Question: A Node.js 26 process was started with `--permission --allow-fs-read=*`. Can it call `process.permission.drop('fs.read', '/etc/myapp')` to revoke read access to just that directory? If not, what can it do instead? In which version was `process.permission.drop()` added?

Answer:
- No. The docs say that when a permission was granted with a wildcard (`*`), individual paths cannot be dropped. Only the entire scope can be dropped, by calling `drop()` without a reference. So `process.permission.drop('fs.read', '/etc/myapp')` does not revoke just that directory.
- What it can do instead:
  - Drop the whole read scope with `process.permission.drop('fs.read')`. This is irreversible and revokes all file system read permission, not only `/etc/myapp`. The pattern in the docs is to read the config at startup and then drop the scope.
  - Restart with narrower grants (for example `--allow-fs-read=<specific paths>`) instead of `*`. A directory grant can be dropped only as the exact directory that was granted, and only that directory's grant is removed.
- Dropping a permission affects only future access checks. Already-open file descriptors and other resources stay open and must be closed by the application.
- `process.permission.drop()` was added in v26.3.0 (marked Stability 1.1, Active Development).

REFs:
- `node:process#processpermissiondropscope-reference`
- `node:permissions#permissiondropscope-reference`

Confidence: high
