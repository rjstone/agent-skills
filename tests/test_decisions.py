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


import json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class FakeSystemOne:
    """Local stand-in for System One hosts. script[path] is a list of
    (status, body) replies used in order; the last one repeats."""

    def __init__(self):
        self.script = {}
        self.requests = []  # (path, headers dict, body dict)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw or b"null")
                except ValueError:
                    body = None
                fake.requests.append((self.path, dict(self.headers), body))
                replies = fake.script.get(self.path) or [(404, {"error": "no route"})]
                status, out = replies.pop(0) if len(replies) > 1 else replies[0]
                if callable(out):
                    out = out(self.headers, body)
                data = out if isinstance(out, bytes) else json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = _reply
            do_GET = _reply

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def calls(self, path):
        return [r for r in self.requests if r[0] == path]


QUESTIONS = {
    "urgent": {"type": "noul", "instructions": "Is this urgent?"},
    "team": {"type": "choice", "criteria": {"ops": "outages", "billing": "payments"}},
}


def good_answer(model="jev-1.14.0"):
    return {"model": model,
            "answers": {"urgent": {"type": "noul", "noul": 0.97},
                        "team": {"type": "choice", "choice": "ops", "confidence": 0.9,
                                 "probabilities": {"ops": 0.95, "billing": 0.05}}},
            "usage": {"input_tokens": 50, "output_tokens": 2}}


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSystemOne()
        self.addCleanup(self.fake.close)
        self.setup = {
            "provider": "a", "model": "jev-1.13-free",
            "fallbacks": [{"provider": "b", "model": "jev-latest"}],
            "questions": QUESTIONS,
            "providers": {
                "a": {"endpoint": self.fake.base + "/a", "key_env": [], "default_model": "jev-1.13-free"},
                "b": {"endpoint": self.fake.base + "/b", "key_env": [], "default_model": "jev-latest"},
            },
            "privacy": {"a": {"confirmed": "2026-11-23"}, "b": {"confirmed": "2026-11-23"}},
        }

    def ev(self, **kw):
        return decide.evaluate("server down", QUESTIONS, setup=self.setup, timeout=5, **kw)

    def test_evaluate_success_meta(self):
        self.fake.script["/a"] = [(200, good_answer())]
        answers, meta = self.ev()
        self.assertEqual(answers["urgent"]["noul"], 0.97)
        self.assertEqual(meta["provider"], "a")
        self.assertEqual(meta["model_requested"], "jev-1.13-free")
        self.assertEqual(meta["model_returned"], "jev-1.14.0")
        self.assertEqual(meta["usage"]["input_tokens"], 50)
        self.assertEqual(meta["hops"], [])

    def test_bearer_header_sent_from_env(self):
        self.setup["providers"]["a"]["key_env"] = ["DECIDE_TEST_KEY_A"]
        os.environ["DECIDE_TEST_KEY_A"] = "placeholder"
        self.addCleanup(os.environ.pop, "DECIDE_TEST_KEY_A", None)
        self.fake.script["/a"] = [(200, good_answer())]
        self.ev()
        headers = self.fake.calls("/a")[0][1]
        self.assertEqual(headers.get("Authorization"), "Bearer placeholder")

    def test_fallback_on_429_then_success(self):
        self.fake.script["/a"] = [(429, {"error": "rate"})]
        self.fake.script["/b"] = [(200, good_answer())]
        answers, meta = self.ev()
        self.assertEqual(meta["provider"], "b")
        self.assertEqual(len(meta["hops"]), 1)
        self.assertIn("429", meta["hops"][0])

    def test_no_fallback_on_422(self):
        self.fake.script["/a"] = [(422, {"detail": "bad question"})]
        self.fake.script["/b"] = [(200, good_answer())]
        with self.assertRaises(decide.DecisionError) as cm:
            self.ev()
        self.assertEqual(cm.exception.kind, "request")
        self.assertIn("bad question", str(cm.exception))
        self.assertEqual(self.fake.calls("/b"), [])

    def test_200_without_answers_retried_once_then_fallback(self):
        self.fake.script["/a"] = [(200, {"model": "x"})]
        self.fake.script["/b"] = [(200, good_answer())]
        _, meta = self.ev()
        self.assertEqual(len(self.fake.calls("/a")), 2)
        self.assertEqual(meta["provider"], "b")

    def test_invalid_answer_is_fallback(self):
        bad = []
        missing = good_answer(); del missing["answers"]["team"]; bad.append(missing)
        nan = good_answer(); nan["answers"]["urgent"]["noul"] = float("nan"); bad.append(nan)
        big = good_answer(); big["answers"]["urgent"]["noul"] = 1.5; bad.append(big)
        wrong = good_answer(); wrong["answers"]["urgent"]["type"] = "score"; bad.append(wrong)
        for body in bad:
            with self.subTest(body=body):
                self.fake.requests.clear()
                self.fake.script["/a"] = [(200, json.dumps(body, allow_nan=True).encode())]
                self.fake.script["/b"] = [(200, good_answer())]
                _, meta = self.ev()
                self.assertEqual(meta["provider"], "b")

    def test_each_hop_uses_its_own_model(self):
        self.fake.script["/a"] = [(503, {"error": "down"})]
        self.fake.script["/b"] = [(200, good_answer())]
        self.ev(model="jev-1.13")
        self.assertEqual(self.fake.calls("/a")[0][2]["model"], "jev-1.13")
        self.assertEqual(self.fake.calls("/b")[0][2]["model"], "jev-latest")

    def test_privacy_refused_without_entry(self):
        del self.setup["privacy"]["a"]
        self.fake.script["/a"] = [(200, good_answer())]
        with self.assertRaises(decide.DecisionError) as cm:
            self.ev()
        self.assertEqual(cm.exception.kind, "privacy")
        self.assertEqual(self.fake.requests, [])
        answers, _ = self.ev(test_data=True)
        self.assertIn("urgent", answers)

    def test_no_setup_needs_test_data(self):
        with self.assertRaises(decide.DecisionError) as cm:
            decide.evaluate("x", QUESTIONS, provider="typesafe")
        self.assertEqual(cm.exception.kind, "privacy")

    def test_fallback_hop_without_privacy_skipped(self):
        del self.setup["privacy"]["b"]
        self.fake.script["/a"] = [(429, {"error": "rate"})]
        self.fake.script["/b"] = [(200, good_answer())]
        with self.assertRaises(decide.DecisionError) as cm:
            self.ev()
        self.assertEqual(cm.exception.kind, "fallback")
        self.assertIn("privacy", str(cm.exception))
        self.assertEqual(self.fake.calls("/b"), [])

    def test_fallback_must_share_family(self):
        self.setup["fallbacks"] = [{"provider": "b", "model": "pplx-decider-latest"}]
        with self.assertRaises(decide.DecisionError) as cm:
            self.ev()
        self.assertEqual(cm.exception.kind, "config")
        self.assertEqual(self.fake.requests, [])

    def test_missing_key_skips_hop(self):
        self.setup["providers"]["a"]["key_env"] = ["DECIDE_TEST_UNSET_KEY"]
        os.environ.pop("DECIDE_TEST_UNSET_KEY", None)
        self.fake.script["/b"] = [(200, good_answer())]
        _, meta = self.ev()
        self.assertEqual(meta["provider"], "b")
        self.assertIn("DECIDE_TEST_UNSET_KEY", meta["hops"][0])

    def test_key_not_in_errors(self):
        self.setup["providers"]["a"]["key_env"] = ["DECIDE_TEST_KEY_A"]
        os.environ["DECIDE_TEST_KEY_A"] = "sk-verysecret-123"
        self.addCleanup(os.environ.pop, "DECIDE_TEST_KEY_A", None)
        self.fake.script["/a"] = [(400, lambda h, b: {"echo": h.get("Authorization")})]
        with self.assertRaises(decide.DecisionError) as cm:
            self.ev()
        self.assertNotIn("sk-verysecret-123", str(cm.exception))

    def test_connection_refused_is_fallback(self):
        self.setup["providers"]["a"]["endpoint"] = "http://127.0.0.1:9/nothing"
        self.fake.script["/b"] = [(200, good_answer())]
        _, meta = self.ev()
        self.assertEqual(meta["provider"], "b")


class RoutingTest(unittest.TestCase):
    def noul(self, v):
        return {"type": "noul", "noul": v}

    def test_route_noul_bands(self):
        rules = [{"question": "q", "reject_below": 0.2, "pass_above": 0.8}]
        self.assertEqual(decide.route({"q": self.noul(0.1)}, rules), "reject")
        self.assertEqual(decide.route({"q": self.noul(0.5)}, rules), "review")
        self.assertEqual(decide.route({"q": self.noul(0.9)}, rules), "pass")

    def test_route_without_pass_above_reviews(self):
        rules = [{"question": "q", "reject_below": 0.2}]
        self.assertEqual(decide.route({"q": self.noul(0.99)}, rules), "review")

    def test_route_any_reject_wins_then_review(self):
        rules = [{"question": "a", "reject_below": 0.2, "pass_above": 0.8},
                 {"question": "b", "reject_below": 0.2, "pass_above": 0.8}]
        self.assertEqual(decide.route({"a": self.noul(0.1), "b": self.noul(0.9)}, rules), "reject")
        self.assertEqual(decide.route({"a": self.noul(0.5), "b": self.noul(0.9)}, rules), "review")
        self.assertEqual(decide.route({"a": self.noul(0.9), "b": self.noul(0.9)}, rules), "pass")

    def test_route_low_confidence_reviews(self):
        rules = [{"question": "s", "reject_below": 0.5, "pass_above": 2.0, "min_confidence": 0.5}]
        a = {"s": {"type": "score", "score": 2.8, "confidence": 0.4, "probabilities": {}}}
        self.assertEqual(decide.route(a, rules), "review")

    def test_route_score_uses_expected_score(self):
        rules = [{"question": "s", "reject_below": 0.5, "pass_above": 2.5}]
        a = {"s": {"type": "score", "score": 2.6, "confidence": 0.9,
                   "probabilities": {"0": 0.1, "1": 0.45, "2": 0.0, "3": 0.45}}}
        self.assertEqual(decide.route(a, rules), "pass")

    def test_choice_rule_maps_names(self):
        rules = [{"question": "team", "routes": {"ops": "pass", "sales": "reject"},
                  "min_confidence": 0.7}]
        def ans(choice, conf):
            return {"team": {"type": "choice", "choice": choice, "confidence": conf,
                             "probabilities": {}}}
        self.assertEqual(decide.route(ans("ops", 0.9), rules), "pass")
        self.assertEqual(decide.route(ans("sales", 0.9), rules), "reject")
        self.assertEqual(decide.route(ans("ops", 0.5), rules), "review")
        self.assertEqual(decide.route(ans("billing", 0.99), rules), "review")

    def test_question_without_rule_is_informational(self):
        rules = [{"question": "a", "reject_below": 0.2, "pass_above": 0.8}]
        a = {"a": self.noul(0.9), "other": self.noul(0.0)}
        self.assertEqual(decide.route(a, rules), "pass")

    def test_missing_answer_reviews(self):
        rules = [{"question": "a", "reject_below": 0.2, "pass_above": 0.8}]
        self.assertEqual(decide.route({}, rules), "review")


class CautiousTest(unittest.TestCase):
    Q = {"n": {"type": "noul"}, "c": {"type": "choice", "criteria": {"x": None, "y": None}},
         "s": {"type": "score", "criteria": ["a", "b", "c", "d"]}}

    def rule(self, rules, name):
        return [r for r in rules if r["question"] == name][0]

    def test_cautious_widens_never_narrows(self):
        pol = {"rules": [{"question": "n", "reject_below": 0.10, "pass_above": 0.70}]}
        r = self.rule(decide.effective_rules(pol, self.Q, True), "n")
        self.assertEqual((r["reject_below"], r["pass_above"]), (0.05, 0.90))
        pol = {"rules": [{"question": "n", "reject_below": 0.01, "pass_above": 0.95}]}
        r = self.rule(decide.effective_rules(pol, self.Q, True), "n")
        self.assertEqual((r["reject_below"], r["pass_above"]), (0.01, 0.95))
        pol = {"rules": [{"question": "c", "routes": {"x": "pass"}, "min_confidence": 0.5},
                         {"question": "s", "min_confidence": 0.8}]}
        rules = decide.effective_rules(pol, self.Q, True)
        self.assertEqual(self.rule(rules, "c")["min_confidence"], 0.6)
        self.assertEqual(self.rule(rules, "s")["min_confidence"], 0.8)

    def test_calibrated_rules_unchanged(self):
        pol = {"rules": [{"question": "n", "reject_below": 0.10, "pass_above": 0.70}]}
        self.assertEqual(decide.effective_rules(pol, self.Q, False), pol["rules"])

    def test_cautious_score_defaults(self):
        pol = {"rules": [{"question": "s"}]}
        r = self.rule(decide.effective_rules(pol, self.Q, True), "s")
        self.assertEqual((r["reject_below"], r["pass_above"]), (0.5, 2.5))

    def test_is_cautious_reasons(self):
        self.assertTrue(decide.is_cautious({"policy": {"mode": "cautious"}})[0])
        self.assertTrue(decide.is_cautious({"policy": {"mode": "calibrated"}})[0])
        cal = {"policy": {"mode": "calibrated"}, "calibration": {"model": "jev-1.13-free"}}
        self.assertFalse(decide.is_cautious(cal, "jev-1.14.0")[0])
        on, why = decide.is_cautious(cal, "perplexity/pplx-decider-flash-v1.3")
        self.assertTrue(on)
        self.assertIn("family", why)


if __name__ == "__main__":
    unittest.main()
