"""Offline tests for skills/decisions/scripts/decide.py.

No network: HTTP tests use a local fake System One server. Run from the repo
root: python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _select import selected  # noqa: E402

if not selected("decisions"):
    raise unittest.SkipTest("decisions not selected (SKILLS)")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "decisions")
SCRIPT = os.path.join(SKILL_DIR, "scripts", "decide.py")

spec = importlib.util.spec_from_file_location("decide", SCRIPT)
decide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decide)


class ProviderTableTest(unittest.TestCase):
    def test_version_constant(self):
        self.assertEqual(decide.VERSION, "0.1.0")

    def test_builtin_providers(self):
        p = decide.PROVIDERS
        self.assertEqual(set(p), {"typesafe", "openrouter", "opencode", "asi", "perplexity"})
        self.assertEqual(p["typesafe"]["endpoint"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(p["openrouter"]["endpoint"], "https://openrouter.ai/api/v1/systemone")
        self.assertEqual(p["opencode"]["endpoint"],
                         "https://opencode.ai/inference/systemone/v1/systemone")
        self.assertEqual(p["asi"]["endpoint"], "https://inference.asicloud.cudos.org/v1/systemone")
        self.assertEqual(p["perplexity"]["endpoint"], "https://api.perplexity.ai/v1/decisions")
        self.assertEqual(p["typesafe"]["key_env"], ["TYPESAFE_AI_API_KEY", "TYPESAFE_API_KEY"])
        self.assertEqual(p["perplexity"]["key_env"], ["PERPLEXITY_API_KEY"])
        self.assertEqual(p["asi"]["key_env"], ["ASI_API_KEY"])
        for name, cfg in p.items():
            self.assertTrue(cfg["verified"], name)
            self.assertTrue(cfg["default_model"], name)

    def test_family_of(self):
        for m in ("jev-1.13-free", "jev-latest", "typesafe/jev-1.14", "~typesafe/jev-latest"):
            self.assertEqual(decide.family_of(m), "jev", m)
        for m in ("perplexity/pplx-decider-flash-v1.3:free", "pplx-decider-latest"):
            self.assertEqual(decide.family_of(m), "pplx-decider", m)
        self.assertEqual(decide.family_of("liquid/d1.2"), "liquid-d1")
        self.assertEqual(decide.family_of("unknown/model"), "unknown/model")

    def test_setup_provider_block_unverified(self):
        setup = {"providers": {"liquid": {"endpoint": "https://example.com/v1/systemone",
                                          "key_env": ["LIQUID_API_KEY"],
                                          "default_model": "d1.1"}}}
        cfg = decide.provider_config("liquid", setup)
        self.assertFalse(cfg["verified"])
        self.assertEqual(cfg["endpoint"], "https://example.com/v1/systemone")
        self.assertTrue(decide.provider_config("typesafe")["verified"])

    def test_unknown_provider_is_config_error(self):
        with self.assertRaises(decide.DecisionError) as cm:
            decide.provider_config("nope")
        self.assertEqual(cm.exception.kind, "config")

    def test_api_key_first_found(self):
        cfg = decide.provider_config("typesafe")
        old = {k: os.environ.pop(k, None) for k in cfg["key_env"]}
        try:
            self.assertIsNone(decide.api_key(cfg))
            os.environ["TYPESAFE_API_KEY"] = "second"
            self.assertEqual(decide.api_key(cfg), "second")
            os.environ["TYPESAFE_AI_API_KEY"] = "first"
            self.assertEqual(decide.api_key(cfg), "first")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


class RequestBuildingTest(unittest.TestCase):
    def test_build_state_with_reference(self):
        self.assertEqual(decide.build_state("defs", {"text": "x"}),
                         {"reference": "defs", "item": {"text": "x"}})
        self.assertEqual(decide.build_state(None, "x"), "x")

    def test_build_request_shape(self):
        q = {"urgent": {"type": "noul", "instructions": "Urgent?"}}
        req = decide.build_request("jev-latest", "text", q)
        self.assertEqual(set(req), {"model", "state", "questions"})
        self.assertEqual(req["questions"], q)


class RedactTest(unittest.TestCase):
    def test_redact_given_secret(self):
        out = decide.redact("Bearer sk-abc123 failed sk-abc123", "sk-abc123")
        self.assertNotIn("sk-abc123", out)

    def test_redact_authorization_pattern(self):
        out = decide.redact('{"echo": "Authorization: Bearer zzzsecretzzz"}')
        self.assertNotIn("zzzsecretzzz", out)

    def test_redact_ignores_empty_secret(self):
        self.assertEqual(decide.redact("plain text", None, ""), "plain text")


if __name__ == "__main__":
    unittest.main()
