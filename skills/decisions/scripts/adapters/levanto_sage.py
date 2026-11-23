"""SAMPLE adapter: System One questions -> Levanto Sage /decide, and back.

Not tested against the live service. Start here only if a user must use Sage;
check every field against Sage's current docs first.

Known differences from System One (from earlier hands-on notes):
- the request is {"model", "content", "questions": [{"question": {"kind", ...}}]}
  with kinds yesno | choice | scale (also sort, tags: not mapped here)
- answers come back by POSITION, in the order the questions were sent
- yes/no, choice and tags return a null answer on a near-tie: treat it as
  "send to review", never as a low-probability answer
- scale levels are distinct integers in the request's own units; this adapter
  sends 0..n-1 so scores line up with System One
- limits: choice 2-120 options (20 with an image), scale 2-26 levels,
  about 32K tokens of context; 402 means the plan's usage is used up

Same contract as every adapter: evaluate(state, questions, *, key, model,
timeout) returns System One-shaped answers, so decide.route() works unchanged.
"""
import json
import urllib.request

ENDPOINT = "https://sage.levanto.ai/decide"


def _text(x):
    if x is None or isinstance(x, str):
        return x or ""
    return json.dumps(x, ensure_ascii=False)


def _question(q):
    t = q.get("type")
    instr = _text(q.get("instructions"))
    crit = q.get("criteria")
    if t == "noul":
        if isinstance(crit, dict):
            instr += f"\nYes means: {_text(crit.get('true'))}\nNo means: {_text(crit.get('false'))}"
        return {"kind": "yesno", "text": instr.strip()}
    if t == "choice":
        return {"kind": "choice", "text": instr,
                "options": [{"name": k, "description": _text(v)} for k, v in (crit or {}).items()]}
    if t == "score":
        return {"kind": "scale", "text": instr,
                "levels": [{"value": i, "description": _text(c)} for i, c in enumerate(crit or [])]}
    raise ValueError(f"question type {t!r} has no Sage equivalent in this adapter")


def to_request(model, state, questions):
    """Returns (request, names): names gives the position of each question."""
    names = list(questions)
    content = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
    req = {"model": model, "content": [{"kind": "text", "text": content}],
           "questions": [{"question": _question(questions[n])} for n in names]}
    return req, names


def from_response(reply, names, questions):
    answers = {}
    for name, a in zip(names, reply.get("answers") or []):
        t = questions[name].get("type")
        value, prob = a.get("answer"), a.get("probability")
        if t == "noul":
            if value is None:
                answers[name] = {"type": "choice", "choice": None, "confidence": 0, "null_answer": True}
            else:
                p = prob if isinstance(prob, (int, float)) else (1.0 if value else 0.0)
                answers[name] = {"type": "noul", "noul": p if value else 1 - p}
        elif t == "choice":
            if value is None:
                answers[name] = {"type": "choice", "choice": None, "confidence": 0, "null_answer": True}
            else:
                answers[name] = {"type": "choice", "choice": value, "confidence": prob or 0,
                                 "probabilities": a.get("probabilities") or {}}
        elif t == "score":
            answers[name] = {"type": "score", "score": a.get("expectation", value),
                             "confidence": a.get("confidence", prob or 0),
                             "probabilities": a.get("probabilities") or {}}
    return answers


def evaluate(state, questions, *, key, model, timeout=60):
    # Delete the next line once your code calls decide.check_privacy() for this service first.
    raise RuntimeError("sample adapter: call decide.check_privacy() before evaluate(), then delete this line")
    req, names = to_request(model, state, questions)
    http_req = urllib.request.Request(ENDPOINT, data=json.dumps(req).encode("utf-8"), method="POST",
                                      headers={"Content-Type": "application/json",
                                               "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(http_req, timeout=timeout) as r:  # nosec B310 - fixed https endpoint
        return from_response(json.loads(r.read().decode("utf-8")), names, questions)
