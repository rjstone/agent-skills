"""SAMPLE adapter: System One questions -> Levanto Sage /decide/batch, and back.

Request shape checked against the live API on 2026-11-23 (yesno, choice and
scale, one item per call; model levanto-sage-2, chosen by the server).

How Sage differs from System One:
- POST /decide/batch {"requests": [{"content": <str or object>,
  "questions": [{"kind", "id", "instructions", ...}]}]}; no "model" field
- kinds: yesno, choice (options [{"option", "description"}]), scale
  (levels [{"level": int, "description"}]); also sort and tags, not mapped
- answers come back per question with its id: {"ok", "result", "error"}
- yesno: {"answer": "yes"|"no"|null, "probability": p of that answer};
  choice: {"chosen", "probability", "probabilities": [{"option", "probability"}]};
  scale: {"expectation", "confidence", "probabilities": [{"level", "probability"}]}
- a null answer means a near-tie: send it to review, never treat it as a low
  probability; a question with "ok": false is left out (decide.route -> review)
- limits seen in its docs: choice 2-120 options (20 with an image), scale
  2-26 levels, about 32K tokens of context; 402 means the plan's usage is used up

Same contract as every adapter: evaluate(state, questions, *, key, model,
timeout) returns System One-shaped answers ("model" is ignored: Sage picks it).
"""
import json
import urllib.request

ENDPOINT = "https://sage.levanto.ai/decide/batch"


def _text(x):
    if x is None or isinstance(x, str):
        return x or ""
    return json.dumps(x, ensure_ascii=False)


def _question(name, q):
    t = q.get("type")
    instr = _text(q.get("instructions")) or name
    crit = q.get("criteria")
    if t == "noul":
        if isinstance(crit, dict):
            instr += f"\nYes means: {_text(crit.get('true'))}\nNo means: {_text(crit.get('false'))}"
        return {"kind": "yesno", "id": name, "instructions": instr.strip()}
    if t == "choice":
        opts = [{"option": k, **({"description": _text(v)} if v else {})} for k, v in (crit or {}).items()]
        return {"kind": "choice", "id": name, "instructions": instr, "options": opts}
    if t == "score":
        return {"kind": "scale", "id": name, "instructions": instr,
                "levels": [{"level": i, "description": _text(c)} for i, c in enumerate(crit or [])]}
    raise ValueError(f"question type {t!r} has no Sage equivalent in this adapter")


def to_request(state, questions):
    return {"requests": [{"content": state,
                          "questions": [_question(n, q) for n, q in questions.items()]}]}


def from_response(reply, questions):
    answers = {}
    for item in ((reply.get("results") or [{}])[0].get("answers") or []):
        res = item.get("result") or {}
        name = res.get("id")
        if not item.get("ok") or name not in questions:
            continue
        r = res.get("result") or {}
        kind = res.get("kind")
        if kind == "yesno":
            if r.get("answer") is None:
                answers[name] = {"type": "choice", "choice": None, "confidence": 0, "null_answer": True}
            else:
                p = r.get("probability", 0.5)
                answers[name] = {"type": "noul", "noul": p if r["answer"] == "yes" else 1 - p}
        elif kind == "choice":
            if r.get("chosen") is None:
                answers[name] = {"type": "choice", "choice": None, "confidence": 0, "null_answer": True}
            else:
                answers[name] = {"type": "choice", "choice": r["chosen"],
                                 "confidence": r.get("probability", 0),
                                 "probabilities": {x["option"]: x["probability"]
                                                   for x in r.get("probabilities") or []}}
        elif kind == "scale":
            answers[name] = {"type": "score", "score": r.get("expectation"),
                             "confidence": r.get("confidence", 0),
                             "probabilities": {str(x["level"]): x["probability"]
                                               for x in r.get("probabilities") or []}}
    return answers


def evaluate(state, questions, *, key, model=None, timeout=60):
    # Delete the next line once your code calls decide.check_privacy() for this service first.
    raise RuntimeError("sample adapter: call decide.check_privacy() before evaluate(), then delete this line")
    req = urllib.request.Request(ENDPOINT, data=json.dumps(to_request(state, questions)).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json",
                                                         "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - fixed https endpoint
        return from_response(json.loads(r.read().decode("utf-8")), questions)
