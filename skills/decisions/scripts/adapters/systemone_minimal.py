"""SAMPLE: the smallest useful System One call, for reading, not for production.

One POST with {model, state, questions}; the reply's "answers" hold a
probability per question. No fallbacks, cache, validation or routing: use
decide.py for real work. Same contract as the other adapters:
evaluate(state, questions, *, key, model, timeout) returns System One answers.
"""
import json
import urllib.request

ENDPOINT = "https://opencode.ai/inference/systemone/v1/systemone"  # any System One host


def to_request(model, state, questions):
    return {"model": model, "state": state, "questions": questions}


def from_response(reply):
    return reply["answers"]


def evaluate(state, questions, *, key, model, timeout=60, endpoint=ENDPOINT):
    # Delete the next line once your code calls decide.check_privacy() for this service first.
    raise RuntimeError("sample adapter: call decide.check_privacy() before evaluate(), then delete this line")
    req = urllib.request.Request(
        endpoint, data=json.dumps(to_request(model, state, questions)).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - fixed https endpoint
        return from_response(json.loads(r.read().decode("utf-8")))


# Example (made-up text only until the privacy check is done):
#   evaluate("My server is down", {"urgent": {"type": "noul", "instructions": "Is this urgent?"}},
#            key=os.environ["OPENCODE_API_KEY"], model="jev-1.13-free")
#   -> {"urgent": {"type": "noul", "noul": 0.97}}
