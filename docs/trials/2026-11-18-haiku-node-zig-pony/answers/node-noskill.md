# Node.js 26.3.1 questions (answered from memory, no tools)

## N1. path.basename('/foo/bar/baz/asdf/quux.html', '.html')

Answer: `'quux'`

Confidence: high

## N2. node:sqlite DatabaseSync options

- `enableForeignKeyConstraints`: default `true`. Confidence: medium-high. I believe it was added in v22.10.0 and is on by default.
- `defensive`: default `true`. Confidence: medium on the default value.
- Versions in which `defensive` became enabled by default: not sure. I could not place the exact version(s) with confidence. Best guess is that it was added in a 24.x/25.x line and turned on by default later, possibly in 26.x. Confidence: low. Check the Node.js changelog for `node:sqlite` before relying on this.

## N3. process.permission.drop() with --permission --allow-fs-read=*

- Can it revoke read access to just `/etc/myapp`? Probably not. My understanding is that `drop()` only removes existing grants at runtime and cannot carve an exception out of a wildcard grant. `--allow-fs-read=*` is a blanket grant, and I don't think a single subpath can be removed from it. Confidence: medium-low.
- What it can do instead: either (a) restart the process without `--allow-fs-read=*` and pass an explicit list of allowed paths that excludes `/etc/myapp`, or (b) call `process.permission.drop('fs.read', '*')` to remove all read grants, which is far broader than what was asked. Confidence: medium-low.
- Version in which `process.permission.drop()` was added: I believe it was in the v25.x line (around v25.4.0), possibly backported. Confidence: low.
