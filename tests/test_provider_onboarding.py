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


PK_PRICING = {
    "default": {"pricing_config": {"pay_as_you_go": {"request_token": {"price": 0}}}},
    "acme-large": {"pricing_config": {
        "pay_as_you_go": {"request_token": {"price": 0.00015}, "response_token": {"price": 0.0006},
                          "cache_read_input_token": {"price": 0.000075},
                          "additional_units": {"web_search": {"price": 1}}},
        "batch_config": {"request_token": {"price": 0.000075}}}},
}
PK_GENERAL = {"name": "acme", "default": {"params": [
    {"key": "max_tokens", "defaultValue": 128, "minValue": 1, "maxValue": 8192},
    {"key": "stream", "defaultValue": True, "type": "boolean"}]}}


class PortkeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = os.path.join(self.tmp.name, "api.json")
        json.dump(API, open(self.api, "w"))
        self.pk = os.path.join(self.tmp.name, "portkey")
        for kind, data in (("pricing", PK_PRICING), ("general", PK_GENERAL)):
            os.makedirs(os.path.join(self.pk, kind))
            json.dump(data, open(os.path.join(self.pk, kind, "acme.json"), "w"))

    def test_cents_per_token_become_usd_per_million(self):
        self.assertEqual(lookup.per_million(0.00025), 2.5)
        p = lookup.portkey_pricing(PK_PRICING["acme-large"])
        self.assertEqual(p["input"], 1.5)
        self.assertEqual(p["output"], 6.0)
        self.assertEqual(p["cache_read"], 0.75)
        self.assertEqual(p["batch_input"], 0.75)
        self.assertEqual(p["per_unit_usd"], {"web_search": 0.01})

    def test_provider_names_map_then_fall_back_to_id(self):
        self.assertEqual(lookup.portkey_names("mistral"), ["mistral-ai", "mistral"])
        self.assertEqual(lookup.portkey_names("openai"), ["openai"])

    def test_model_key_matching(self):
        self.assertEqual(lookup.portkey_model_key("acme/acme-large", PK_PRICING), "acme-large")
        self.assertIsNone(lookup.portkey_model_key("zzz", PK_PRICING))

    def test_api_tried_first_then_github_fallback(self):
        calls = []

        def fake_fetch(url, cache_dir, refresh):
            calls.append(url)
            if url.startswith(lookup.PORTKEY_BASES[0]):
                raise RuntimeError("blocked")
            return PK_PRICING, "network"

        args = type("A", (), {"portkey_dir": None, "cache_dir": self.tmp.name, "refresh": False})()
        orig = lookup.fetch
        lookup.fetch = fake_fetch
        try:
            data, src, errors = lookup.portkey_load("pricing", "acme", args)
        finally:
            lookup.fetch = orig
        self.assertEqual(calls, ["https://configs.portkey.ai/pricing/acme.json",
                                 "https://raw.githubusercontent.com/Portkey-AI/models/main/pricing/acme.json"])
        self.assertIs(data, PK_PRICING)
        self.assertIn("raw.githubusercontent.com", src)
        self.assertEqual(len(errors), 1)

    def test_cli_card_shows_portkey_section(self):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "-p", "acme", "-m", "acme-large",
                            "--portkey-dir", self.pk, "--format", "json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        pk = json.loads(r.stdout)["entries"][0]["portkey"]
        self.assertEqual(pk["model_key"], "acme-large")
        self.assertEqual(pk["pricing_usd"]["output"], 6.0)
        self.assertEqual(pk["params"], {"max_tokens": {"min": 1, "max": 8192, "default": 128}})

    def test_missing_portkey_file_is_reported_not_fatal(self):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "-p", "relay",
                            "--portkey-dir", self.pk], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no Portkey pricing file for relay", r.stdout)

    def test_default_output_has_no_portkey(self):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "-p", "acme", "--format", "json"],
                           capture_output=True, text=True)
        self.assertNotIn("portkey", json.loads(r.stdout)["entries"][0])


EXTRA = [
    {"slug": "zeta", "name": "Zeta Cloud", "aliases": ["zc"], "category": "Gateway",
     "website": "https://zeta.example", "api_base_url": "https://api.zeta.example/v1/",
     "env_variable": "ZETA_API_KEY", "openai_compatible": True, "notes": "n", "popular_models": ["z1"]},
    {"slug": "zeta-web", "name": "Zeta Web", "category": "Web Cookie",
     "api_base_url": "https://zeta.example/api/chat", "env_variable": "", "openai_compatible": False},
    {"slug": "zeta-free", "name": "Zeta Free", "category": "No-auth",
     "api_base_url": "https://free.zeta.example/v1", "env_variable": "", "openai_compatible": True},
    {"slug": "zeta-hook", "name": "Zeta Hook", "category": "Frontier",
     "api_base_url": "Custom webhooks", "env_variable": "X", "openai_compatible": False},
]


class ExtraListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = os.path.join(self.tmp.name, "api.json")
        json.dump(API, open(self.api, "w"))
        self.extra = os.path.join(self.tmp.name, "providers.json")
        json.dump(EXTRA, open(self.extra, "w"))

    def run_json(self, *args):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "--format", "json",
                            "--extra-list-file", self.extra, *args], capture_output=True, text=True)
        return r

    def test_skips_cookie_noauth_and_non_url_entries(self):
        args = type("A", (), {"extra_list_file": self.extra, "cache_dir": None, "refresh": False})()
        ok, note = lookup.load_extra(args)
        self.assertEqual([p["slug"] for p in ok], ["zeta"])
        self.assertIn("1 usable", note)

    def test_community_only_provider_is_labelled_unverified(self):
        r = self.run_json("-p", "zeta")
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        e = res["entries"][0]
        self.assertEqual(e["base_url"], "https://api.zeta.example/v1")
        self.assertEqual(e["base_url_source"], lookup.EXTRA_TAG)
        self.assertEqual(e["env"], ["ZETA_API_KEY"])
        self.assertEqual(e["protocol"], "openai")
        self.assertTrue(any("community list" in w for w in res["warnings"]))

    def test_alias_matches(self):
        self.assertEqual(json.loads(self.run_json("-p", "zc").stdout)["entries"][0]["provider_id"], "zeta")

    def test_models_dev_match_wins(self):
        e = json.loads(self.run_json("-p", "acme").stdout)["entries"][0]
        self.assertEqual(e["provider_id"], "acme")
        self.assertNotEqual(e["base_url_source"], lookup.EXTRA_TAG)

    def test_skipped_category_not_offered(self):
        r = self.run_json("-p", "zeta-web")
        e = json.loads(r.stdout)["entries"]
        self.assertTrue(all(x["provider_id"] != "zeta-web" for x in e))

    def test_off_by_default(self):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "-p", "zeta"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


LITELLM = {
    "sample_spec": {"input_cost_per_token": 0},
    "acme/acme-large": {"litellm_provider": "acme", "mode": "chat",
                        "input_cost_per_token": 1.5e-06, "output_cost_per_token": 7.0e-06,
                        "cache_read_input_token_cost": 1.5e-07, "input_cost_per_token_batches": 7.5e-07,
                        "input_cost_per_token_above_200k_tokens": 3e-06,
                        "max_input_tokens": 128000, "max_output_tokens": 8192,
                        "supports_function_calling": True, "supports_vision": False,
                        "source": "https://acme-ai.example/pricing",
                        "deprecation_date": "2027-01-01", "successor_model": "acme/acme-xl"},
    "acme/acme-embed": {"litellm_provider": "acme", "mode": "embedding", "input_cost_per_token": 1e-08},
    "acme-large-gemini": {"litellm_provider": "gemini", "mode": "chat", "input_cost_per_token": 1e-06},
}


class LiteLLMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = os.path.join(self.tmp.name, "api.json")
        json.dump(API, open(self.api, "w"))
        self.table = os.path.join(self.tmp.name, "litellm.json")
        json.dump(LITELLM, open(self.table, "w"))

    def card(self, *args):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "--format", "json",
                            "--litellm-file", self.table, *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["entries"][0]["litellm"]

    def test_prices_per_million_and_tiers(self):
        p = lookup.litellm_pricing(LITELLM["acme/acme-large"])
        self.assertEqual(p, {"input": 1.5, "output": 7.0, "cache_read": 0.15,
                             "batch_input": 0.75, "input_above_200k": 3.0})

    def test_prefixed_key_matches_and_embedding_ignored(self):
        key, names = lookup.litellm_match("acme", "acme-large", LITELLM)
        self.assertEqual(key, "acme/acme-large")
        self.assertEqual(lookup.litellm_match("acme", "acme-embed", LITELLM)[0], None)

    def test_provider_map_is_used(self):
        self.assertIn("gemini", lookup.litellm_providers("google", LITELLM))
        self.assertNotIn("gemini", lookup.litellm_providers("acme", LITELLM))

    def test_card_has_source_deprecation_and_disagreement(self):
        ll = self.card("-p", "acme", "-m", "acme-large")
        self.assertEqual(ll["key"], "acme/acme-large")
        self.assertEqual(ll["pricing_source"], "https://acme-ai.example/pricing")
        self.assertEqual(ll["deprecation_date"], "2027-01-01")
        self.assertEqual(ll["successor_model"], "acme/acme-xl")
        self.assertEqual(ll["capabilities"], ["function_calling"])
        self.assertEqual(ll["disagrees_with_models_dev"], ["output: LiteLLM $7 vs models.dev $6"])

    def test_unknown_provider_is_reported(self):
        ll = self.card("-p", "relay")
        self.assertIn("error", ll)

    def test_off_by_default(self):
        r = subprocess.run([sys.executable, SCRIPT, "--file", self.api, "-p", "acme", "-m", "acme-large",
                            "--format", "json"], capture_output=True, text=True)
        self.assertNotIn("litellm", json.loads(r.stdout)["entries"][0])
