"""SAMPLE adapter: System One questions -> Vercel AI Gateway /v1/evaluate, and back.

Answers not yet seen live. Checked 2026-11-23: the endpoint and a Bearer key
work, but every decision model needs paid AI Gateway credits (403 "Free tier
users do not have access to this model"; the old free id
convaiinnovations/laya-free is gone, and "providerOptions": {"gateway":
{"has": ["free"]}} finds no free provider). Check every field against
Vercel's current docs before use.

Known differences from System One (from earlier hands-on notes):
- yes/no questions are type "boolean", not "noul"
- "instructions" must be a plain string
- score criteria are ordered label strings; choice/boolean criteria are {name: string}
- Laya (convaiinnovations/laya) has an 8K context and answered 422 on large
  payloads in earlier tests
- model ids are provider/model slugs (for example "convaiinnovations/laya")

Same contract as every adapter: evaluate(state, questions, *, key, model,
timeout) returns System One-shaped answers, so decide.route() works unchanged.
"""
import json
import urllib.request

ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"


def _text(x):
    if x is None or isinstance(x, str):
        return x or ""
    return json.dumps(x, ensure_ascii=False)


def to_request(model, state, questions):
    out = {}
    for name, q in questions.items():
        t = q.get("type")
        nq = {"type": "boolean" if t == "noul" else t, "instructions": _text(q.get("instructions"))}
        crit = q.get("criteria")
        if t == "score":
            nq["criteria"] = [_text(c) for c in crit or []]
        elif isinstance(crit, dict):
            nq["criteria"] = {k: _text(v) or k for k, v in crit.items()}
        out[name] = nq
    return {"model": model, "state": state, "questions": out}


def from_response(reply):
    answers = {}
    for name, a in (reply.get("answers") or {}).items():
        if a.get("type") == "boolean":
            p = a.get("boolean", a.get("probability", a.get("noul")))
            answers[name] = {"type": "noul", "noul": p}
        else:
            answers[name] = a
    return answers


def evaluate(state, questions, *, key, model, timeout=60):
    # Delete the next line once your code calls decide.check_privacy() for this service first.
    raise RuntimeError("sample adapter: call decide.check_privacy() before evaluate(), then delete this line")
    body = json.dumps(to_request(model, state, questions)).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - fixed https endpoint
        return from_response(json.loads(r.read().decode("utf-8")))
