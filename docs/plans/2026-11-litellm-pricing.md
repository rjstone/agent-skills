# LiteLLM pricing in provider-onboarding (2026-11-18)

Compared LiteLLM's `model_prices_and_context_window.json` with models.dev and
Portkey: more providers than Portkey (about 157 vs 54), a pricing-page link on
most chat entries, deprecation dates and successors, tiered prices. Not a
provider directory (no env vars or reliable base URLs), so models.dev stays
the card's base.

Done (0.4.0): `--litellm` / `--litellm-file` as the main detailed-pricing
source, flagging disagreements with models.dev; Portkey kept as a second
opinion (the user, 2026-11-18). Offline tests use a fixture table.
