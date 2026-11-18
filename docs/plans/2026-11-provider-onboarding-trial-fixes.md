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
