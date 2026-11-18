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

## Round 3 (typesafe jev, "a decision model that isn't jev", muse wonder)

Answers were good (Jev via gateways, gpt-oss-120b as the reasoning pick,
Muse Wonder at $4 / $20 from 12 providers). Fixed in the same PR:

1. A name that is not a chat model (Jev, a `decision` model) said "No model
   matches"; the lookup now retries with all types and names the type.
2. Output price / limit 0 labelled as "not billed or not published".
3. SKILL.md: model ids differ by provider; reuse the id from the model search.
4. Portkey says which location failed and how (blocked vs 404).

Added (the user, 2026-11-18): categories. `--type` (models.dev `type`:
chat, decision, image, embedding, video, transcription, speech, reranking,
realtime), `--input-modality` / `--output-modality`, a browse table grouped
across providers, `--list-types`. A `typesafe` override from Typesafe's public
docs (base URL, key variable, website, its own decisions API protocol), and
override `protocols` lists without OpenAI/Anthropic now set the card's protocol.

## Round 4 (vague category requests: "a decent decision model", "the cheapest decision model", "some inexpensive text-to-speech models")

All three agents found `--type` on their own (Jev / Gemini Decision 1; Decider
Flash V1.3 at $0.01; Gemini 3.8 Flash-Lite TTS). Version bumped to 0.6.0 (the
user, 2026-11-18). Fixed:

1. Browse rows name where the cheapest price is listed (provider: id);
   `--sort price`.
2. Snippets follow the model type (speech, transcription, embedding, image;
   decision and others point at the docs; no chat smoke test for non-chat).
3. LiteLLM only matches modes that fit the model type (a TTS model never takes
   a chat model's price); LiteLLM and Portkey near-misses are marked "closest
   match" with no disagreement report; Portkey needs a strong match.
4. Override-only providers (TypeSafe) say "no model list in the data".
5. Zero output wording: "not published, or not billed".
6. SKILL.md: check ids against a provider's own API (jev vs jev-latest), TTS
   price units, and never quote a closest-match price.
