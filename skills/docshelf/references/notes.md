# Writing docvol notes

Keep durable lessons (gotchas, project conventions) in the docvol's notes
file. Find it with `notes DOCVOL --path` (creates the notes folder; the
file itself appears when you write it), and edit it with normal file tools.
Notes are shared by every release of a docvol: `python~3.13` and
`python~3.14` both use `python.md`, so `notes python --path` works for either.

Format: a `## General` section (optional), plus `## <entry name>` sections:
the name as `search` prints it, or its part before `(` (`## asyncio.gather`
covers `asyncio.gather()`; `## open (Function)` covers that one entry,
`## open` all its variants), with an optional ` (Type)` suffix to
disambiguate. A heading may also be a heading inside a page, matched the
same way: when a docvol indexes whole sections (DuckDB), `## count_if`
matches the `count_if(x)` heading on the section's page. Only `show` prints
notes: General, the section for the entry, and the sections for headings
inside what `show` printed (General alone for a REF that is not an entry),
so many small sections are cheap and one big one is not.

Run `notes DOCVOL --check` after editing: it lists which `show` REFs print
each section (so there's no need to `show` the entry to confirm; for a page
heading it lists the REF of that heading), and warns about oversized notes
and headings that match no entry or page heading. On a size warning,
suggest to the user turning the heavy section into its own minimal skill
built around the tasks it covers.
