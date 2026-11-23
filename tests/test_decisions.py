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

    def test_privacy_error_lists_three_confirmations(self):
        with self.assertRaises(decide.DecisionError) as cm:
            decide.check_privacy("opencode", {"privacy": {}}, False)
        msg = str(cm.exception)
        for words in ("OK to send", "retention and training terms", "agree"):
            self.assertIn(words, msg)

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


import tempfile  # noqa: E402
from unittest import mock  # noqa: E402


class SetupFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "leads.decisions.json")

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_load_setup_missing_questions_names_key(self):
        self.write({"provider": "typesafe"})
        with self.assertRaises(decide.DecisionError) as cm:
            decide.load_setup(self.path)
        self.assertEqual(cm.exception.kind, "config")
        self.assertIn("questions", str(cm.exception))

    def test_load_setup_defaults_model(self):
        self.write({"provider": "opencode", "questions": QUESTIONS})
        self.assertEqual(decide.load_setup(self.path)["model"], "jev-1.13-free")

    def test_load_setup_bad_json_is_config_error(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        with self.assertRaises(decide.DecisionError) as cm:
            decide.load_setup(self.path)
        self.assertEqual(cm.exception.kind, "config")

    def test_save_setup_roundtrip(self):
        decide.save_setup(self.path, {"provider": "opencode", "questions": QUESTIONS})
        self.assertEqual(decide.load_setup(self.path)["provider"], "opencode")

    def test_save_setup_atomic(self):
        self.write({"provider": "opencode", "questions": QUESTIONS, "marker": 1})
        with mock.patch.object(decide.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                decide.save_setup(self.path, {"provider": "x", "questions": {}})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["marker"], 1)
        self.assertEqual(os.listdir(self.dir.name), ["leads.decisions.json"])

    def test_record_privacy_fields(self):
        setup = decide.record_privacy({}, "opencode", "https://example.com/privacy",
                                      "keeps prompts 30 days", "2026-11-23")
        entry = setup["privacy"]["opencode"]
        self.assertEqual(entry, {"confirmed": "2026-11-23",
                                 "policy_url": "https://example.com/privacy",
                                 "summary": "keeps prompts 30 days"})


class CacheTest(unittest.TestCase):
    def test_cache_key_changes_with_questions_and_reference(self):
        k = decide.cache_key("p", "m", QUESTIONS, "ref", "item")
        self.assertNotEqual(k, decide.cache_key("p", "m", {"x": {"type": "noul"}}, "ref", "item"))
        self.assertNotEqual(k, decide.cache_key("p", "m", QUESTIONS, "ref2", "item"))
        self.assertNotEqual(k, decide.cache_key("p", "m2", QUESTIONS, "ref", "item"))
        self.assertNotEqual(k, decide.cache_key("p", "m", QUESTIONS, "ref", "item2"))

    def test_cache_key_stable_across_dict_order(self):
        a = {"x": {"type": "noul", "instructions": "i"}, "y": {"type": "noul"}}
        b = {"y": {"type": "noul"}, "x": {"instructions": "i", "type": "noul"}}
        self.assertEqual(decide.cache_key("p", "m", a, None, {"b": 1, "a": 2}),
                         decide.cache_key("p", "m", b, None, {"a": 2, "b": 1}))

    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.sqlite")
            c = decide.Cache(path)
            self.assertIsNone(c.get("k"))
            c.put("k", {"q": {"type": "noul", "noul": 0.5}}, "jev-1.14.0")
            c.close()
            got = decide.Cache(path).get("k")
            self.assertEqual(got["answers"]["q"]["noul"], 0.5)
            self.assertEqual(got["model_returned"], "jev-1.14.0")
        self.assertIsNone(decide.Cache(None).get("k"))
        decide.Cache(None).put("k", {}, "m")

    def test_default_cache_path(self):
        self.assertEqual(decide.default_cache_path(os.path.join("a", "leads.decisions.json")),
                         os.path.join("a", "leads.decisions.cache.sqlite"))


import contextlib  # noqa: E402
import io  # noqa: E402


class CliTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSystemOne()
        self.addCleanup(self.fake.close)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.setup_path = os.path.join(self.dir.name, "t.decisions.json")
        self.setup = {
            "provider": "a", "model": "jev-1.13-free", "questions": QUESTIONS,
            "reference": "ops means outages",
            "policy": {"mode": "cautious",
                       "rules": [{"question": "urgent", "reject_below": 0.2, "pass_above": 0.8}]},
            "providers": {"a": {"endpoint": self.fake.base + "/a", "key_env": [],
                                "default_model": "jev-1.13-free"}},
            "privacy": {"a": {"confirmed": "2026-11-23"}},
        }
        self.save()
        self.fake.script["/a"] = [(200, self.answer_for)]

    def save(self):
        with open(self.setup_path, "w", encoding="utf-8") as f:
            json.dump(self.setup, f)

    @staticmethod
    def answer_for(headers, body):
        text = json.dumps(body["state"])
        p = 0.99 if "fire" in text else (0.01 if "spam" in text else 0.5)
        a = good_answer()
        a["answers"]["urgent"]["noul"] = p
        return a

    def write(self, name, text, mode="w"):
        path = os.path.join(self.dir.name, name)
        with open(path, mode) as f:
            f.write(text)
        return path

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = decide.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def rows(self, out):
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def test_run_jsonl_routes_and_summary(self):
        src = self.write("in.jsonl", '{"id": "1", "text": "fire in server room"}\n'
                                     '{"id": "2", "text": "spam offer"}\n'
                                     '{"id": "3", "text": "question about invoice"}\n')
        code, out, err = self.main("run", self.setup_path, "--input", src, "--no-cache")
        self.assertEqual(code, 0, err)
        routes = {r["id"]: r["route"] for r in self.rows(out)}
        self.assertEqual(routes, {"1": "pass", "2": "reject", "3": "review"})
        self.assertIn("mode: cautious", err)
        self.assertIn("pass 1", err)
        body = self.fake.calls("/a")[0][2]
        self.assertEqual(body["state"]["reference"], "ops means outages")
        self.assertEqual(body["state"]["item"], {"text": "fire in server room"})

    def test_run_bad_lines_reported(self):
        src = self.write("in.jsonl", b'{"id": "1", "text": "fire"}\n\n{"text": "no id"}\n'
                                     b'{"id": "4", "text": "\xff\xfe bad"}\n'
                                     b'{"id": "5", "text": "fire again"}\n', "wb")
        code, out, err = self.main("run", self.setup_path, "--input", src, "--no-cache")
        rows = self.rows(out)
        errors = [r for r in rows if r["error"]]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("line 3" in r["error"] for r in errors))
        self.assertTrue(any("line 4" in r["error"] for r in errors))
        self.assertTrue(all(r["route"] == "review" for r in errors))
        self.assertEqual([r["id"] for r in rows if not r["error"]], ["1", "5"])

    def test_run_csv_and_dir_inputs(self):
        src = self.write("in.csv", "id,text\n1,fire\n2,spam\n")
        code, out, err = self.main("run", self.setup_path, "--input", src, "--no-cache")
        self.assertEqual([r["route"] for r in self.rows(out)], ["pass", "reject"])
        folder = os.path.join(self.dir.name, "posts")
        os.mkdir(folder)
        for name, text in (("b.txt", "spam"), ("a.md", "fire")):
            with open(os.path.join(folder, name), "w") as f:
                f.write(text)
        code, out, err = self.main("run", self.setup_path, "--input", folder, "--no-cache")
        self.assertEqual([(r["id"], r["route"]) for r in self.rows(out)],
                         [("a.md", "pass"), ("b.txt", "reject")])

    def test_run_uses_cache_second_time(self):
        src = self.write("in.jsonl", '{"id": "1", "text": "fire"}\n')
        self.main("run", self.setup_path, "--input", src)
        n = len(self.fake.requests)
        code, out, err = self.main("run", self.setup_path, "--input", src)
        self.assertEqual(len(self.fake.requests), n)
        self.assertTrue(self.rows(out)[0]["cached"])

    def test_run_failed_item_goes_to_review(self):
        self.fake.script["/a"] = [(503, {"error": "down"})]
        src = self.write("in.jsonl", '{"id": "1", "text": "fire"}\n')
        code, out, err = self.main("run", self.setup_path, "--input", src, "--no-cache")
        self.assertEqual(code, 4)
        row = self.rows(out)[0]
        self.assertEqual(row["route"], "review")
        self.assertIn("503", row["error"])

    def test_dry_run_sends_nothing_and_needs_no_key(self):
        del self.setup["privacy"]
        self.setup["providers"]["a"]["key_env"] = ["DECIDE_TEST_UNSET_KEY"]
        self.save()
        src = self.write("in.jsonl", '{"id": "1", "text": "fire"}\n')
        code, out, err = self.main("run", self.setup_path, "--input", src, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["model"], "jev-1.13-free")
        self.assertEqual(self.fake.requests, [])

    def test_run_refuses_without_privacy_exit_3(self):
        del self.setup["privacy"]
        self.save()
        src = self.write("in.jsonl", '{"id": "1", "text": "fire"}\n')
        code, out, err = self.main("run", self.setup_path, "--input", src)
        self.assertEqual(code, 3)
        self.assertIn("privacy", err)
        self.assertEqual(self.fake.requests, [])

    def test_ask_requires_setup_or_test_data(self):
        code, out, err = self.main("ask", "--provider", "typesafe", "--state", "x", "--yes", "Urgent?")
        self.assertEqual(code, 3)
        self.fake.script["/a"] = [(200, {"model": "m", "usage": {},
                                         "answers": {"answer": {"type": "noul", "noul": 0.97}}})]
        code, out, err = self.main("ask", self.setup_path, "--state", "fire", "--yes", "Urgent?")
        self.assertEqual(code, 0, err)
        self.assertIn("Yes", out)
        self.assertIn("%", out)

    def test_ask_choice_and_score_plain_language(self):
        def reply(h, body):
            q = body["questions"]
            name = list(q)[0]
            if q[name]["type"] == "choice":
                a = {"type": "choice", "choice": "ops", "confidence": 0.9,
                     "probabilities": {"ops": 0.97, "billing": 0.03}}
            else:
                a = {"type": "score", "score": 2.6, "confidence": 0.82,
                     "probabilities": {}, "legend": {}}
            return {"model": "m", "answers": {name: a}, "usage": {}}
        self.fake.script["/a"] = [(200, reply)]
        code, out, err = self.main("ask", self.setup_path, "--state", "x",
                                   "--choice", "ops=outages", "billing=payments")
        self.assertEqual(code, 0, err)
        self.assertIn("ops (97%)", out)
        self.assertIn("billing (3%)", out)
        code, out, err = self.main("ask", self.setup_path, "--state", "x",
                                   "--score", "junk", "weak", "plausible", "strong")
        self.assertIn("2.6", out)

    def test_providers_lists_names_only(self):
        os.environ["OPENROUTER_API_KEY"] = "sk-or-secret-value"
        self.addCleanup(os.environ.pop, "OPENROUTER_API_KEY", None)
        code, out, err = self.main("providers")
        self.assertEqual(code, 0)
        self.assertIn("openrouter", out)
        self.assertIn("OPENROUTER_API_KEY", out)
        self.assertNotIn("sk-or-secret-value", out + err)

    def test_privacy_subcommand_writes_entry(self):
        code, out, err = self.main("privacy", self.setup_path, "--provider", "b",
                                   "--policy-url", "https://example.com/p", "--summary", "30 days")
        self.assertEqual(code, 0, err)
        entry = decide.load_setup(self.setup_path)["privacy"]["b"]
        self.assertEqual(entry["policy_url"], "https://example.com/p")

    def test_version_flag(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                decide.main(["--version"])
        self.assertIn("0.1.0", out.getvalue())


class CalibrationTest(unittest.TestCase):
    Q = {"real": {"type": "noul", "instructions": "real lead?"}}

    def setup_(self, **kw):
        s = {"provider": "a", "model": "jev-1.13-free", "questions": self.Q,
             "policy": {"mode": "cautious", "good_if": [{"question": "real", "is": True}],
                        "rules": [{"question": "real", "source": "calibration"}]},
             "privacy": {"a": {"confirmed": "2026-11-23"}}}
        s.update(kw)
        return s

    @staticmethod
    def scorer_from(values, model="jev-1.14.0"):
        def scorer(state, questions, **kw):
            item = state["item"] if isinstance(state, dict) and "item" in state else state
            return values[item], {"provider": "a", "model_returned": model, "usage": {}, "hops": []}
        return scorer

    def labeled(self, good_vals, bad_vals):
        labels, values = [], {}
        for i, v in enumerate(good_vals):
            labels.append({"id": f"g{i}", "item": f"g{i}", "expected": {"real": True}})
            values[f"g{i}"] = {"real": {"type": "noul", "noul": v}}
        for i, v in enumerate(bad_vals):
            labels.append({"id": f"b{i}", "item": f"b{i}", "expected": {"real": False}})
            values[f"b{i}"] = {"real": {"type": "noul", "noul": v}}
        return labels, values

    def test_auroc_known_values(self):
        self.assertEqual(decide.auroc([0.9, 0.8, 0.1, 0.2], [True, True, False, False]), 1.0)
        self.assertEqual(decide.auroc([0.1, 0.2, 0.9, 0.8], [True, True, False, False]), 0.0)
        self.assertEqual(decide.auroc([0.5, 0.5, 0.5, 0.5], [True, True, False, False]), 0.5)
        self.assertIsNone(decide.auroc([0.5, 0.6], [True, True]))

    def test_is_good(self):
        g = [{"question": "real", "is": True}, {"question": "q", "at_least": 2},
             {"question": "c", "in": ["ops", "billing"]}]
        self.assertTrue(decide.is_good({"real": True, "q": 2, "c": "ops"}, g))
        self.assertFalse(decide.is_good({"real": True, "q": 1, "c": "ops"}, g))
        self.assertFalse(decide.is_good({"real": True, "q": 3, "c": "sales"}, g))
        self.assertFalse(decide.is_good({"q": 3, "c": "ops"}, g))

    def test_suggest_reject_keeps_target_recall(self):
        good = [0.30 + 0.69 * i / 19 for i in range(20)]
        bad = [0.01 + 0.39 * i / 19 for i in range(20)]
        labels, values = self.labeled(good, bad)
        setup = self.setup_()
        report = decide.calibrate(setup, labels, scorer=self.scorer_from(values))
        rule = [r for r in setup["policy"]["rules"] if r["question"] == "real"][0]
        rejected_good = sum(v < rule["reject_below"] for v in good)
        self.assertLessEqual(rejected_good, 1)
        self.assertGreater(sum(v < rule["reject_below"] for v in bad), 5)
        self.assertEqual(rule["source"], "calibration")
        self.assertGreaterEqual(report["item_recall"], 0.95)

    def test_item_level_recall_loosens_rules(self):
        q = {"a": {"type": "noul"}, "b": {"type": "noul"}}
        labels, values = [], {}
        for i in range(20):
            va = 0.05 if i == 0 else 0.6 + i / 100
            vb = 0.05 if i == 1 else 0.6 + i / 100
            labels.append({"id": f"g{i}", "item": f"g{i}", "expected": {"a": True, "b": True}})
            values[f"g{i}"] = {"a": {"type": "noul", "noul": va}, "b": {"type": "noul", "noul": vb}}
        for i in range(10):
            labels.append({"id": f"b{i}", "item": f"b{i}", "expected": {"a": False, "b": False}})
            values[f"b{i}"] = {"a": {"type": "noul", "noul": 0.01}, "b": {"type": "noul", "noul": 0.01}}
        setup = self.setup_(questions=q, policy={"mode": "cautious", "good_if": [
            {"question": "a", "is": True}, {"question": "b", "is": True}], "rules": []})
        report = decide.calibrate(setup, labels, scorer=self.scorer_from(values))
        rules = setup["policy"]["rules"]
        good_rejected = sum(
            decide.route(values[f"g{i}"], rules) == "reject" for i in range(20))
        self.assertLessEqual(good_rejected, 1)
        self.assertGreaterEqual(report["item_recall"], 0.95)

    def test_pass_above_none_when_precision_unreachable(self):
        good = [0.5 + i / 100 for i in range(10)]
        bad = [0.5 + i / 100 for i in range(10)]
        labels, values = self.labeled(good, bad)
        setup = self.setup_()
        decide.calibrate(setup, labels, scorer=self.scorer_from(values))
        rule = setup["policy"]["rules"][0]
        self.assertNotIn("pass_above", rule)

    def test_pass_above_set_when_separable(self):
        labels, values = self.labeled([0.9, 0.92, 0.95, 0.97, 0.99] * 4, [0.1, 0.2, 0.3] * 5)
        setup = self.setup_()
        decide.calibrate(setup, labels, scorer=self.scorer_from(values))
        self.assertIn("pass_above", setup["policy"]["rules"][0])

    def test_choice_min_confidence_from_accuracy(self):
        q = {"code": {"type": "choice", "criteria": {"6100": None, "6200": None}}}
        labels, values = [], {}
        for i in range(20):
            conf = 0.5 + i / 40
            right = conf >= 0.7
            exp = "6100"
            got = exp if right else "6200"
            labels.append({"id": str(i), "item": str(i), "expected": {"code": exp}})
            values[str(i)] = {"code": {"type": "choice", "choice": got, "confidence": conf,
                                       "probabilities": {}}}
        setup = self.setup_(questions=q, policy={"mode": "cautious", "rules": []})
        report = decide.calibrate(setup, labels, scorer=self.scorer_from(values))
        rule = setup["policy"]["rules"][0]
        self.assertGreaterEqual(rule["min_confidence"], 0.65)
        self.assertLessEqual(rule["min_confidence"], 0.75)
        self.assertEqual(report["questions"]["code"]["confusion"]["6100"]["6200"], 8)
        self.assertEqual(decide.route(values["19"], [rule]), "pass")
        self.assertEqual(decide.route(values["0"], [rule]), "review")

    def test_calibrate_keeps_user_rules_unless_replace(self):
        labels, values = self.labeled([0.6 + i / 100 for i in range(20)], [0.1] * 10)
        user = {"question": "real", "reject_below": 0.3, "pass_above": 0.5, "source": "user"}
        setup = self.setup_(policy={"mode": "cautious", "good_if": [{"question": "real", "is": True}],
                                    "rules": [dict(user)]})
        report = decide.calibrate(setup, labels, scorer=self.scorer_from(values))
        self.assertEqual(setup["policy"]["rules"], [user])
        self.assertEqual(report["kept_user_rules"][0]["question"], "real")
        decide.calibrate(setup, labels, scorer=self.scorer_from(values), replace_user_rules=True)
        self.assertEqual(setup["policy"]["rules"][0]["source"], "calibration")

    def test_calibrate_warns_small_label_sets(self):
        labels, values = self.labeled([0.9] * 10, [0.1, 0.2])
        report = decide.calibrate(self.setup_(), labels, scorer=self.scorer_from(values))
        text = " ".join(report["warnings"])
        self.assertIn("12 labels", text)
        self.assertIn("not good", text)

    def test_calibrate_records_returned_model_and_counts(self):
        labels, values = self.labeled([0.9] * 15, [0.1] * 10)
        setup = self.setup_()
        decide.calibrate(setup, labels, scorer=self.scorer_from(values), today="2026-11-23")
        cal = setup["calibration"]
        self.assertEqual(cal["model"], "jev-1.14.0")
        self.assertEqual(cal["labels"], 25)
        self.assertEqual(cal["counts"], {"good": 15, "not good": 10})
        self.assertEqual(cal["date"], "2026-11-23")
        self.assertEqual(setup["policy"]["mode"], "calibrated")
        self.assertFalse(decide.is_cautious(setup, "jev-1.14.0")[0])

    def test_calibrate_respects_privacy(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.decisions.json")
            setup = self.setup_()
            del setup["privacy"]
            setup["providers"] = {"a": {"endpoint": "http://127.0.0.1:9/x", "key_env": []}}
            with open(path, "w") as f:
                json.dump(setup, f)
            lab = os.path.join(d, "labels.jsonl")
            with open(lab, "w") as f:
                f.write('{"id": "1", "item": "x", "expected": {"real": true}}\n')
            with contextlib.redirect_stderr(io.StringIO()):
                code = decide.main(["calibrate", path, "--labels", lab])
            self.assertEqual(code, 3)


def _load_adapter(name):
    path = os.path.join(SKILL_DIR, "scripts", "adapters", name + ".py")
    sp = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


class AdapterTest(unittest.TestCase):
    Q = {"urgent": {"type": "noul", "instructions": {"question": "Urgent?"},
                    "criteria": {"true": "outage", "false": "anything else"}},
         "team": {"type": "choice", "criteria": {"ops": "outages", "sales": None}},
         "quality": {"type": "score", "criteria": ["junk", "ok", "great"]}}

    def test_vercel_to_request_uses_boolean(self):
        v = _load_adapter("vercel_evaluate")
        req = v.to_request("convaiinnovations/laya", "text", self.Q)
        q = req["questions"]
        self.assertEqual(q["urgent"]["type"], "boolean")
        self.assertIsInstance(q["urgent"]["instructions"], str)
        self.assertEqual(q["quality"]["criteria"], ["junk", "ok", "great"])
        self.assertTrue(all(isinstance(x, str) for x in q["team"]["criteria"].values()))
        ans = v.from_response({"answers": {"urgent": {"type": "boolean", "boolean": 0.8}}})
        self.assertEqual(ans["urgent"], {"type": "noul", "noul": 0.8})

    def test_sage_null_answer_maps_to_review_marker(self):
        sg = _load_adapter("levanto_sage")
        names = ["team"]
        ans = sg.from_response({"answers": [{"answer": None, "probability": 0.5}]}, names,
                               {"team": self.Q["team"]})
        self.assertTrue(ans["team"]["null_answer"])
        self.assertEqual(ans["team"]["confidence"], 0)
        self.assertEqual(decide.route(ans, [{"question": "team"}]), "review")

    def test_sage_score_levels_without_level_key(self):
        sg = _load_adapter("levanto_sage")
        req, names = sg.to_request("levanto-sage-v1.3", {"text": "x"}, self.Q)
        self.assertEqual(names, ["urgent", "team", "quality"])
        kinds = [q["question"]["kind"] for q in req["questions"]]
        self.assertEqual(kinds, ["yesno", "choice", "scale"])
        self.assertEqual([lv["value"] for lv in req["questions"][2]["question"]["levels"]], [0, 1, 2])


class SetupValidationTest(unittest.TestCase):
    def check(self, setup, word):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.decisions.json")
            with open(path, "w") as f:
                json.dump(setup, f)
            with self.assertRaises(decide.DecisionError) as cm:
                decide.load_setup(path)
            self.assertEqual(cm.exception.kind, "config")
            self.assertIn(word, str(cm.exception))

    def base(self, **kw):
        s = {"provider": "opencode", "questions": dict(QUESTIONS)}
        s.update(kw)
        return s

    def test_questions_must_be_object(self):
        self.check(self.base(questions=[{"id": "q", "type": "noul"}]), "object")

    def test_question_type_known(self):
        self.check(self.base(questions={"q": {"type": "yesno"}}), "noul, choice, score")

    def test_choice_criteria_object_and_score_criteria_list(self):
        self.check(self.base(questions={"q": {"type": "choice", "criteria": ["a", "b"]}}), "criteria")
        self.check(self.base(questions={"q": {"type": "score", "criteria": {"a": 1}}}), "criteria")

    def test_good_if_must_be_list_of_conditions(self):
        self.check(self.base(policy={"good_if": "a good lead"}), "good_if")

    def test_rule_names_unknown_question(self):
        self.check(self.base(policy={"rules": [{"question": "nope"}]}), "nope")

    def test_combine_value(self):
        self.check(self.base(policy={"combine": "some"}), "combine")

    def test_example_setup_is_valid(self):
        decide.load_setup(os.path.join(SKILL_DIR, "examples", "lead-vetting.decisions.json"))


class CombineAnyTest(unittest.TestCase):
    RULES = [{"question": "harassment", "reject_below": 0.1, "pass_above": 0.8},
             {"question": "spam", "reject_below": 0.1, "pass_above": 0.8}]

    def a(self, h, s):
        return {"harassment": {"type": "noul", "noul": h}, "spam": {"type": "noul", "noul": s}}

    def test_any_pass_flags_even_if_others_reject(self):
        self.assertEqual(decide.route(self.a(0.95, 0.01), self.RULES, combine="any"), "pass")
        self.assertEqual(decide.route(self.a(0.95, 0.01), self.RULES), "reject")

    def test_any_rejects_only_when_all_reject(self):
        self.assertEqual(decide.route(self.a(0.02, 0.01), self.RULES, combine="any"), "reject")
        self.assertEqual(decide.route(self.a(0.5, 0.01), self.RULES, combine="any"), "review")

    def test_any_without_rules_reviews(self):
        self.assertEqual(decide.route({}, [], combine="any"), "review")

    def test_run_uses_policy_combine(self):
        setup = {"policy": {"combine": "any", "rules": self.RULES}}
        self.assertEqual(decide.combine_of(setup), "any")
        self.assertEqual(decide.combine_of({}), "all")


if __name__ == "__main__":
    unittest.main()
