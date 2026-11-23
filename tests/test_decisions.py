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


if __name__ == "__main__":
    unittest.main()
