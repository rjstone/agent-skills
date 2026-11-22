---
name: skillspector-install
description: Use when asked whether an AI agent skill, skill folder, archive, repo or MCP server is safe, trustworthy, installable, over-permissioned or malicious, or to scan one with NVIDIA SkillSpector, and the skill-inspector skill or the skillspector command isn't installed yet.
compatibility: Needs network access to github.com and PyPI, Node.js (npx) for the skill, and git. Installs uv if missing; uv fetches Python 3.13 itself.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.1"
  credits: "NVIDIA SkillSpector"
---

# SkillSpector install

[NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector) is a security
scanner for agent skills and MCP servers: 71 rules (prompt injection,
exfiltration, privilege escalation, supply chain, MCP tool poisoning, YARA
signatures, ...) that produce a risk score, findings and a recommendation.
Upstream ships a companion agent skill, `skill-inspector`, that runs the
scanner and adds a source-level review and an APPROVE / CAUTION / REJECT
verdict. This skill only installs both.

## Install

Check first: `skillspector --version`. If it prints the version you want and
`skill-inspector` is in your skills list, skip to "Next".

Otherwise run the install script (from this skill's folder):

```bash
python scripts/install.py                 # skill + scanner, pinned to v2.13.6
python scripts/install.py --install-mcp   # also the [mcp] extra + `claude mcp add`
python scripts/install.py --dry-run       # print the commands, change nothing
```

What it does, in order:

1. Finds `uv`; if missing, installs a pinned uv from its GitHub release
   without editing shell profiles (it prints a PATH hint instead).
2. `uv tool install --python 3.13 skillspector@<ref>` from GitHub. Python
   3.12/3.13 is needed for prebuilt YARA wheels; uv downloads it. Skipped
   when the installed version already matches (`--force` reinstalls). A
   reinstall keeps the `[mcp]` extra if it was installed before or an MCP
   server named `skillspector` exists, so a registered server keeps working.
3. `npx skills@1.9.0 add` (pinned CLI) the `skill-inspector` skill at the
   same ref, user scope (`-g`), for `--agent claude-code` (repeat `--agent`
   for other harnesses).
4. With `--install-mcp`: the `[mcp]` extra, then
   `claude mcp add --scope user skillspector -- <path>/skillspector mcp`.

Other options: `--ref TAG` (another release), `--skip-skill`,
`--skip-scanner`, `--mcp-scope local|user|project`, `--python 3.12`.
`python scripts/install.py --help` lists them all.

## Failure modes

- **`skillspector: command not found` after a successful install:** uv's tool
  folder isn't on PATH. The script prints it; run `uv tool update-shell` or
  call the full path.
- **YARA build errors:** a Python other than 3.12/3.13 was used. Keep the
  default `--python 3.13`.
- **`npx` missing:** install Node.js, or use `--skip-skill` and install
  `skill-inspector` by hand later.
- **Network blocked** (sandbox or CI): the script needs github.com,
  PyPI and Python downloads; it stops at the first failed step and names it.
- **MCP not visible:** restart the agent session; `claude mcp list` should
  show `skillspector`.

## Next

1. Restart the agent session (or reload skills) so `skill-inspector` loads.
2. Read and follow `skill-inspector` for every review: it is the usage
   guide (scan with `--no-llm`, read the report, review the source, verdict).
3. Command reference: `skillspector scan --help` and the upstream
   [README](https://github.com/NVIDIA/SkillSpector#readme).
