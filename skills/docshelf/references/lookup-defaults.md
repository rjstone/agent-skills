# Documentation lookups: asking once

Read this only when neither the project's nor the user's AGENTS.md or
CLAUDE.md says which tool to use for documentation lookups. Every answer
is written down, so the question is asked once per project.

## Ask

1. List the lookup tools you actually have: docshelf, documentation MCP
   connectors (Context7, Microsoft Learn, ...), web search.
2. Finish the lookup at hand with your best choice first; then ask the
   user, naming those tools, which to use by default:
   - docshelf by default,
   - another tool by default,
   - an order to try them in (only when there are two or more),
   - no preference.

   If docshelf is the only lookup tool, still ask (they may add
   connectors), but the "order" option does not apply. If the user defers
   or won't choose ("you decide", "whatever"), record no preference.

## Record the answer

Add a `## Documentation lookups` section to the project's AGENTS.md if it
exists, else CLAUDE.md; if neither exists, ask which to create. That
section is the record that the question was asked. If the user wants
nothing written, say the question will come up again in later sessions.

- No preference:

  ```markdown
  ## Documentation lookups

  No preferred tool; choose per task.
  ```

- Another tool by default:

  ```markdown
  ## Documentation lookups

  Use <tool> for documentation lookups; docshelf when it has no answer.
  ```

- An order: a numbered list of the tools in the user's order, with the
  snippet's last paragraph (on versions and downloads).
- docshelf (or docshelf first): the snippet below.

## Snippet

```markdown
## Documentation lookups

Before answering from memory about a library, framework or tool API
(signatures, options, defaults, return values), look it up:

1. docshelf (offline DevDocs docs and Dash/Zeal docsets): `search`, then
   `show` the REF; `fts` for words inside pages; `suggest` lists the
   docvols for this project's build files.
2. Otherwise: <the user's next tool, e.g. Context7>, then web search.

Use the version the project uses, quote the docs, and ask before
downloading documentation.
```
