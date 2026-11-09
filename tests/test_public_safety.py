"""This repo is public: no secrets, personal identifiers or machine details.

Scans every git-tracked text file. Patterns catch the mechanical cases only
(AGENTS.md "Public repo" lists the full criteria; a human review is still
required). Placeholders such as /home/me or user@example.com are allowed.
Run from the repo root: python3 -m unittest discover -s tests -v
"""
import os
import re
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRETS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("API key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("password assignment", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s<>{}$]{8,}['\"]")),
]

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
EMAIL_OK = re.compile(r"(?i)^(?:noreply@|no-reply@)|@(?:example\.(?:com|org|net)|users\.noreply\.github\.com)$")

# absolute home paths with a real-looking account name
HOME = re.compile(r"(?:/home/|/Users/|[A-Za-z]:[\\/]+Users[\\/]+)([A-Za-z0-9._-]+)")
HOME_OK = {"me", "user", "username", "you", "runner", "name", "example", "alice", "bob"}
DRIVE = re.compile(r"(?:^|[^A-Za-z])[A-Za-z]:[\\/]")


def tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True)
    for rel in out.stdout.decode().split("\0"):
        if not rel:
            continue
        try:
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
                yield rel, f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary, or deleted in the working tree


class TestPublicSafety(unittest.TestCase):
    def hits(self, check):
        found = []
        for rel, text in tracked_text_files():
            if rel == "tests/test_public_safety.py":
                continue  # holds the patterns themselves
            for n, line in enumerate(text.splitlines(), 1):
                for what in check(line):
                    found.append(f"{rel}:{n}: {what}")
        return found

    def test_no_secrets(self):
        def check(line):
            return [name for name, rx in SECRETS if rx.search(line)]
        self.assertEqual(self.hits(check), [])

    def test_no_personal_emails(self):
        def check(line):
            return [m.group(0) for m in EMAIL.finditer(line) if not EMAIL_OK.search(m.group(0))]
        self.assertEqual(self.hits(check), [])

    def test_no_account_home_paths(self):
        def check(line):
            return [m.group(0) for m in HOME.finditer(line) if m.group(1).lower() not in HOME_OK]
        self.assertEqual(self.hits(check), [])

    def test_no_drive_letter_paths(self):
        def check(line):
            line = re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://\S+", "", line)  # URLs
            return ["drive-letter path"] if DRIVE.search(line) else []
        self.assertEqual(self.hits(check), [])


if __name__ == "__main__":
    unittest.main()
