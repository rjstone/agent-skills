# docshelf as an MCP server

`python <skill folder>/scripts/docshelf.py --mcp` serves docshelf over the
Model Context Protocol (stdio, stdlib only). `<skill folder>` is where this
skill is installed, the folder that holds `SKILL.md`. Use a full path, and
`python3` where `python` is not Python 3.

Tools: `search`, `show`, `fts`, `list`, `sources`, `install`, `remove` and
`notes`, with the same arguments as the commands (`docsets` is the repeatable
`-d`). `notes` only reads (add `check: true` for the check report); write
notes files directly. `where`, `update` and `index-text` are command line
only. A tool result is the command's output; `isError` is true when the exit
code is not 0.

The server runs in the folder the client starts it in, and finds a project's
`.docshelf.json` from there. `DOCSHELF_CACHE_DIR` and `DOCSHELF_NOTES_DIR`
apply as for the command line.

Use either docshelf's MCP server or another DevDocs MCP server, not both:
two sets of near-identical tools confuse the model.

## Claude Code

```
claude mcp add docshelf -- python <skill folder>/scripts/docshelf.py --mcp
```

## Clients that use `mcpServers` JSON (Claude Desktop, Cursor and others)

```json
{
  "mcpServers": {
    "docshelf": {
      "command": "python",
      "args": ["<skill folder>/scripts/docshelf.py", "--mcp"]
    }
  }
}
```

## Codex (`config.toml`)

```toml
[mcp_servers.docshelf]
command = "python"
args = ["<skill folder>/scripts/docshelf.py", "--mcp"]
```

## opencode (`opencode.json`)

```json
{
  "mcp": {
    "docshelf": {
      "type": "local",
      "command": ["python", "<skill folder>/scripts/docshelf.py", "--mcp"]
    }
  }
}
```
