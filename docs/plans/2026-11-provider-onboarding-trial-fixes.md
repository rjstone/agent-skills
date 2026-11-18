# provider-onboarding: fixes from Haiku trials (2026-11-18)

Three parallel Haiku subagents (default effort) used the 0.4.0 skill for
gpt-oss-120b, kimi-k2 and gemini-2.5-flash. All answered well; they found:

1. `--limit` undocumented; model-only output showed 8 of 59-141 providers.
2. Fuzzy model matches (kimi-k2 -> k2.6, gpt-oss-120b -> 20b) not flagged.
3. Portkey "no file" errors listed every URL tried (very noisy).
4. LiteLLM picked a GovCloud regional Bedrock price; `bedrock_mantle` was
   missing from the provider map; misleading "no provider" message.
5. fast-agent snippets generated for non-OpenAI protocols and missing base URLs.
6. Portkey price disagreements with models.dev not flagged.

Done (0.5.0): all six fixed with tests; SKILL.md tells the agent to read the
warnings, rerun with `--limit`, and never present a closest match as the
requested id. Next: re-run the same three trials to compare.

## Round 2 (same three trials against 0.5.0)

Better answers: all three used `--limit`, flagged closest matches, and the
Gemini agent put the 2026-12-01 retirement first (confirmed on Google's page).
New findings, fixed in the same PR:

- Crash: markdown output with a `${VAR}` base URL (models.dev `neon`) hit
  `None` in `hosts_to_allowlist`; exposed by `--limit 100`. Template hosts
  are now kept as written and labelled.
- `github.com` and `api.aws` treated as shared hosts (no apex sign-up guess).
- Model-only queries list exact matches only when there are some
  (kimi-k2: 6142 -> 500 lines); `--all-matches` shows near matches.
- A LiteLLM retirement date that is past or within 6 months is a top-level
  warning with the successor.

Not done (noted): LiteLLM-only hosts are not listed (the card is built from
models.dev); Portkey's per-URL failure reasons; odd-precision prices from
currency conversion.
