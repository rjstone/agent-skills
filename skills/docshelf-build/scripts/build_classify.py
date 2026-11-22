"""Rules that sort llms.txt pages into reference (full) and guide (stub) from
the per-page signals in the plan. Thresholds were calibrated on the labelled
sample in tests/fixtures/docshelf_build_classify.json (two sites)."""
import html
import re
from typing import Callable, Dict, List, Optional, Tuple

from build_html import main_content
from build_markdown import front_matter

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


def may_decide(page: Dict) -> bool:
    """True when the rules may set this page: it has signals and was not set
    by a person (`manual`, `override:*`) or an agent (`model:` but not rules)."""
    if not isinstance(page.get("signals"), dict):
        return False
    why = page.get("why") or ""
    if why == "manual" or why.startswith("override:"):
        return False
    return not why.startswith("model:") or why.startswith("model:rules-")


def run_rules(plan: Dict) -> None:
    """Apply rule_choice to every page the rules may decide. Idempotent."""
    for page in plan.get("pages", {}).values():
        if not may_decide(page):
            continue
        choice = rule_choice(page["signals"])
        if choice == "review":
            page["keep"] = "full"
            if (page.get("why") or "").startswith("model:rules-"):
                page["why"] = "llms: all"
        else:
            page["keep"] = choice
            page["why"] = RULES_ID


BUCKETS = ("reference", "stub", "person", "agent", "review", "no signals")


def bucket(page: Dict) -> str:
    if not isinstance(page.get("signals"), dict):
        return "no signals"
    why = page.get("why") or ""
    if why == "manual" or why.startswith("override:"):
        return "person"
    if why.startswith("model:rules-"):
        return "stub" if page.get("keep") == "stub" else "reference"
    if why.startswith("model:"):
        return "agent"
    return "review"


def counts(plan: Dict) -> Dict[str, int]:
    out = {b: 0 for b in BUCKETS}
    for page in plan.get("pages", {}).values():
        out[bucket(page)] += 1
    return out


def preview(text: str, kind: str, n: int = 200) -> str:
    """Page text without front matter, tags and the first heading, whitespace
    collapsed, cut to n characters."""
    if not text:
        return ""
    if kind == "html":
        body = main_content(text)
        body = re.sub(r"(?is)<h[1-6][^>]*>.*?</h[1-6]>", " ", body, count=1)
        body = re.sub(r"(?s)<[^>]*>", " ", body)
        body = html.unescape(body)
    else:
        _, body = front_matter(text)
        lines = body.split("\n")
        for i, line in enumerate(lines):
            if line.strip():
                if line.lstrip().startswith("#"):
                    del lines[i]
                break
        body = re.sub(r"(?s)<[^>]*>", "", "\n".join(lines))
    return " ".join(body.split())[:n]


def review_lines(plan: Dict, get_raw: Callable[[str], Optional[Tuple[str, str]]],
                 offset: int, limit: int) -> List[str]:
    """Three lines (two when no preview) per review page, in plan order."""
    keys = [k for k, p in plan.get("pages", {}).items() if bucket(p) == "review"]
    out: List[str] = []
    for key in keys[max(0, offset):max(0, offset) + max(0, limit)]:
        page = plan["pages"][key]
        sig = page["signals"]
        section = "[%s] " % page["section"] if page.get("section") else ""
        out.append("%s   %s%s" % (key, section, page.get("title") or ""))
        out.append("  words=%s code=%s you=%s sig=%s steps=%s tables=%s" % (
            sig.get("words", 0), sig.get("code_ratio", 0), sig.get("you_per_1k", 0),
            sig.get("signature_lines", 0), sig.get("steps", 0), sig.get("tables", 0)))
        got = get_raw(key)
        snippet = preview(got[0], got[1]) if got else ""
        if snippet:
            out.append("  > " + snippet)
    return out
