"""Rules that sort llms.txt pages into reference (full) and guide (stub) from
the per-page signals in the plan. Thresholds were tuned on the labelled
sample in tests/fixtures/docshelf_build_classify.json (calibration and holdout
splits; the fresh split is only a frozen check)."""
import html
import re
from typing import Callable, Dict, List, Optional, Tuple

from build_html import main_content
from build_markdown import front_matter

RULES_ID = "model:rules-2"  # the plan's `why` for a rules decision; bump when thresholds change

MIN_WORDS = 250        # thinner pages carry too little signal: review
REF_MAX_YOU = 3.0      # reference prose rarely addresses the reader ("you" per 1000 words)
REF_MIN_TABLES = 2     # parameter and option tables mark reference (a signature-line
                       # count did not separate guides with code from reference: dropped)
GUIDE_MIN_YOU = 14.0   # tutorial prose talks to the reader; 10 stubbed reference pages
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
    if you <= REF_MAX_YOU and tables >= REF_MIN_TABLES:
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


def parse_choices(text: str) -> Tuple[List[Tuple[int, str, str, Optional[str]]], List[str]]:
    """Parse an agent's choices: `full KEY` or `stub KEY [description]` per line.
    The key REST (upper case, no description) means every page still in review.
    Returns (line number, keep, key, description or None) tuples and errors."""
    choices: List[Tuple[int, str, str, Optional[str]]] = []
    errors: List[str] = []
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.replace("\r", "").strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0] not in ("full", "stub"):
            errors.append("line %d: expected 'full KEY' or 'stub KEY [description]'" % n)
            continue
        desc = parts[2].strip() if len(parts) > 2 else ""
        if parts[1] == "REST" and desc:
            errors.append("line %d: REST takes no description" % n)
            continue
        choices.append((n, parts[0], parts[1], desc or None))
    return choices, errors


def apply_choices(plan: Dict, choices, model_id: str) -> Tuple[int, List[str]]:
    """Apply parsed choices to the plan; the last line for a key wins.
    Pages decided by a person are refused. A REST line is applied last, to the
    pages still in review (even if a page is really named REST); a later line
    without a description keeps the earlier one. Returns (applied, messages)."""
    pages = plan.get("pages", {})
    applied = 0
    messages: List[str] = []
    rest = None
    for n, keep, key, desc in choices:
        if key == "REST":
            rest = keep
            continue
        page = pages.get(key)
        if page is None:
            messages.append("line %d: %s: unknown page" % (n, key))
            continue
        why = page.get("why") or ""
        if why == "manual" or why.startswith("override:"):
            who = "manual" if why == "manual" else "override"
            messages.append("line %d: %s: decided by a person (%s), skipped" % (n, key, who))
            continue
        page["keep"] = keep
        page["why"] = "model:" + model_id
        if desc is not None:
            page["description"] = desc
        applied += 1
    if rest is not None:
        todo = [p for p in pages.values() if bucket(p) == "review"]
        for page in todo:
            page["keep"] = rest
            page["why"] = "model:" + model_id
        applied += len(todo)
        messages.append("REST: %d pages set to %s" % (len(todo), rest))
    return applied, messages
