Service: Firecrawl (chosen as the single search/scrape service; it returned the official nodejs.org docs directly)

N1. path.basename('/foo/bar/baz/asdf/quux.html', '.html') returns 'quux'.
URLs: https://nodejs.org/docs/latest/api/path.html (example in the basename section, shows the same call returning 'quux'); https://nodejs.org/api/path.html (search excerpt).
Confidence: high.

N2. new DatabaseSync(path, options) in node:sqlite:
- enableForeignKeyConstraints defaults to true.
- defensive defaults to true.
- defensive became enabled by default in v25.5.0 and v24.14.0 (the history table reads "v25.5.0, v24.14.0 | Enable `defensive` by default."). The option itself was added in v24.12.0 (per the v24.x docs history table; the v24 history table reads "v24.12.0 | Add `defensive` option."). Older 22.x docs do not list defensive at all.
URLs: https://nodejs.org/api/sqlite.html (current v26.13.1 docs: both defaults true, and the version history for defensive); https://nodejs.org/download/release/latest-v24.x/docs/api/sqlite.html (v24 history: v24.12.0 added, v24.14.0 default-enabled).
Caveat: I did not see a v26.x-specific history line for "enabled by default"; the v25.5.0 and v24.14.0 entry is what the current v26 docs list. The v26 docs show it as default true, so v26 has it on.
Confidence: medium-high (defaults: high; version list: medium, since the excerpts were search snippets and the full sqlite page was too large to scrape).

N3. With --permission --allow-fs-read=*, process.permission.drop('fs.read', '/etc/myapp') will NOT revoke read access to just that directory. The docs say: if a permission was granted with a wildcard (*), only the entire scope can be dropped (drop() with no reference). Also, drop() only works on the exact resource that was granted; you cannot drop a sub-path of a grant.
What it can do instead:
- Call process.permission.drop('fs.read') with no reference to drop read access to the whole fs.read scope (irreversible, all file reads then denied).
- Or restart the process with narrower grants (e.g. --allow-fs-read=/etc/myapp/* plus only the paths it needs) instead of *, and then drop the exact granted reference if needed.
- Or read the config at startup while still permitted (the docs' own example pattern), and then drop the whole fs.read scope.
Version: process.permission.drop() was added in v26.3.0 and v24.20.0 (process.permission.has dates from v20.0.0).
URLs: https://nodejs.org/api/permissions.html (drop semantics, wildcard rule, example); https://nodejs.org/api/process.html (Added in: v26.3.0, v24.20.0); https://beta.docs.nodejs.org/process (same version line).
Confidence: high for the wildcard rule and the version; medium-high for the "instead" options (derived from the documented rules, not a stated recommendation).
