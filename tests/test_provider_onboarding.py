"""Offline tests for skills/provider-onboarding/scripts/lookup.py.

No network: manual mode needs no data, and --file supplies a tiny
models.dev-style api.json. Run from the repo root:
python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("provider-onboarding"):
    raise unittest.SkipTest("provider-onboarding not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "skills", "provider-onboarding", "scripts", "lookup.py")

spec = importlib.util.spec_from_file_location("lookup", SCRIPT)
lookup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lookup)

API = {
    "acme": {
        "id": "acme", "name": "Acme AI", "env": ["ACME_API_KEY"],
        "npm": "@ai-sdk/openai-compatible", "doc": "https://docs.acme-ai.example/models",
        "api": "https://api.acme-ai.example/v1",
        "models": {
            "acme-large": {"id": "acme-large", "name": "Acme Large", "tool_call": True,
                           "limit": {"context": 128000, "output": 8192},
                           "cost": {"input": 1.5, "output": 6.0}},
        },
    },
    "relay": {
        "id": "relay", "name": "Relay Gateway", "env": ["RELAY_KEY"],
        "npm": "@ai-sdk/openai-compatible", "api": "https://relay.example/api/v1",
        "models": {"acme/acme-large": {"id": "acme/acme-large", "name": "Acme Large",
                                       "limit": {"context": 128000, "output": 8192},
                                       "cost": {"input": 2.0, "output": 8.0}}},
    },
}


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.api = os.path.join(self.tmp, "api.json")
        with open(self.api, "w", encoding="utf-8") as f:
            json.dump(API, f)

    def run_lookup(self, *args):
        env = dict(os.environ, MODELS_DEV_URLS="")
        p = subprocess.run([sys.executable, SCRIPT, "--cache-dir", self.tmp, *args],
                           capture_output=True, text=True, env=env, timeout=60)
        return p.returncode, p.stdout, p.stderr

    def test_manual_mode_needs_no_data(self):
        code, out, err = self.run_lookup("--name", "Acme", "--base-url", "https://api.acme-ai.example/v1",
                                         "--env-var", "ACME_API_KEY", "--model-id", "acme-large",
                                         "--format", "json")
        self.assertEqual(code, 0, err)
        e = json.loads(out)["entries"][0]
        self.assertIn("https://api.acme-ai.example/v1", json.dumps(e))
        self.assertIn("ACME_API_KEY", json.dumps(e))

    def test_manual_openai_protocol_uses_openai_compatible_package(self):
        code, out, err = self.run_lookup("--name", "Acme", "--base-url", "https://api.acme-ai.example/v1",
                                         "--env-var", "ACME_API_KEY", "--model-id", "acme-large")
        self.assertEqual(code, 0, err)
        self.assertIn("@opencode/ai/providers/openai-compatible", out)
        self.assertNotIn("@opencode/ai/providers/acme", out)

    def test_file_lookup_finds_model_and_other_servers(self):
        code, out, err = self.run_lookup("--file", self.api, "-p", "acme", "-m", "acme-large", "--format", "json")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        text = json.dumps(res["entries"][0])
        for want in ("acme-large", "https://api.acme-ai.example/v1", "ACME_API_KEY", "128000"):
            self.assertIn(want, text)
        self.assertIn("snippets", res["entries"][0])
        self.assertEqual([a["provider_id"] for a in res["also_served_by"]], ["relay"])

    def test_unknown_provider_exits_2(self):
        code, _, err = self.run_lookup("--file", self.api, "-p", "nosuchprovider")
        self.assertEqual(code, 2)
        self.assertIn("No provider matches", err)

    def test_no_data_and_no_override_exits_3(self):
        code, _, err = self.run_lookup("--overrides", os.path.join(self.tmp, "none.json"), "-m", "acme-large")
        self.assertEqual(code, 3)

    def test_opencode_overrides_use_current_inference_urls(self):
        # Console docs (2026-11-08): https://opencode.ai/inference[/go]/..., no /zen/ paths
        empty = os.path.join(self.tmp, "empty.json")
        with open(empty, "w", encoding="utf-8") as f:
            json.dump({}, f)
        for pid, base in (("opencode", "https://opencode.ai/inference/openai/v1"),
                          ("opencode-go", "https://opencode.ai/inference/go/openai/v1")):
            code, out, err = self.run_lookup("--file", empty, "-p", pid, "--format", "json")
            self.assertEqual(code, 0, err)
            e = json.loads(out)["entries"][0]
            self.assertEqual(e["base_url"], base, pid)
            self.assertNotIn("/zen", out, pid)
            self.assertIn("%s/chat/completions" % base, json.dumps(e["snippets"]), pid)

    def test_signup_inference(self):
        self.assertEqual(lookup.registrable("api.acme-ai.example"), "acme-ai.example")
        self.assertEqual(lookup.registrable("api.example.co.uk"), "example.co.uk")
        self.assertTrue(lookup.is_shared("generativelanguage.googleapis.com"))
        c = lookup.signup_candidates("https://x.googleapis.com/v1", None, {})
        self.assertEqual(c[0]["url"], None)  # shared infra: no apex guess
        c = lookup.signup_candidates("https://api.acme-ai.example/v1", None, {})
        self.assertEqual(c[0]["url"], "https://acme-ai.example")
        self.assertIn("not verified", c[0]["basis"])


if __name__ == "__main__":
    unittest.main()
