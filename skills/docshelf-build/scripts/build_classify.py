"""Rules that sort llms.txt pages into reference (full) and guide (stub) from
the per-page signals in the plan. Thresholds were calibrated on the labelled
sample in tests/fixtures/docshelf_build_classify.json (two sites)."""
from typing import Dict

RULES_ID = "model:rules-1"  # the plan's `why` for a rules decision; bump when thresholds change

MIN_WORDS = 250        # thinner pages carry too little signal: review
REF_MAX_YOU = 3.0      # reference prose rarely addresses the reader ("you" per 1000 words)
REF_MIN_TABLES = 2     # parameter and option tables mark reference
REF_MIN_SIGNATURES = 10  # many signature-like lines mark reference
GUIDE_MIN_YOU = 10.0   # tutorial prose talks to the reader
GUIDE_MAX_TABLES = 1   # a guide may have a table or so, not several


def rule_choice(signals: Dict) -> str:
    """Return "full" (reference), "stub" (guide) or "review" (undecided).
    Missing keys read as 0, so an empty dict is a thin page: review."""
    def g(key: str) -> float:
        value = signals.get(key, 0)
        return value if isinstance(value, (int, float)) else 0

    if g("words") < MIN_WORDS:
        return "review"
    you, tables = g("you_per_1k"), g("tables")
    if you <= REF_MAX_YOU and (tables >= REF_MIN_TABLES
                               or g("signature_lines") >= REF_MIN_SIGNATURES):
        return "full"
    if you >= GUIDE_MIN_YOU and tables <= GUIDE_MAX_TABLES:
        return "stub"
    return "review"
