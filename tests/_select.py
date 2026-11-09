"""Which skills to test. CI sets SKILLS to a comma list (from
scripts/ci_changed_skills.py) so unchanged skills are skipped; unset or
"all" (the default when running locally) means every skill."""
import os


def selected(name):
    value = os.environ.get("SKILLS", "all").strip()
    return value == "all" or name in {s.strip() for s in value.split(",") if s.strip()}
