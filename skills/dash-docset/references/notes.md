# Writing docset notes

Keep durable lessons (gotchas, project conventions) in the docset's notes
file. Find it with `notes DOCSET --path` (creates the `notes/` folder; the
file itself appears when you write it), and edit it with normal file tools.

Format: a `## General` section (optional), plus `## <entry name>` sections:
the name as `search` prints it, or its part before `(` (`## sol.timer.start`
covers `sol.timer.start([context], ...)`; `## SCBNDS (register)` covers that
one entry, `## SCBNDS` all its variants), with an optional ` (Type)` suffix
to disambiguate. Only `show` prints notes: General and the matching section
(General alone for page REFs), so many small sections are cheap and one big
one is not.

Run `notes DOCSET --check` after editing: it lists which `show` REFs print
each section (so there's no need to `show` the entry to confirm), and warns
about oversized notes and headings that match no entry. On a size warning,
suggest to the user turning the heavy section into its own minimal skill
built around the tasks it covers.
