Service: Firecrawl (chosen because its search and scrape tools returned the Pony stdlib 0.38.1 reference pages directly, so each answer could be checked against the page source)

## P1. Printing a line to stdout from Main

Answer: In `actor Main`, take `env: Env` in the constructor (`new create(env: Env) =>`) and call `env.out.print("text")`. The field is `env.out`, declared in class `Env` as `let out: OutStream tag` (the stdout stream, an actor reference with the `tag` capability; the `let` makes the binding read-only).

URLs:
- https://stdlib.ponylang.io/builtin-Env/
- https://tutorial.ponylang.io/getting-started/how-it-works.html (search excerpt only: "that field represents stdout")

Confidence: high

## P2. Declared type of Env.root

Answer: `let root: AmbientAuth val`. The stdlib page says "The root capability." and the `Env.create` constructor says "A root capability must be supplied." Its type is `AmbientAuth val`, a root authority object that is immutable and shareable (`val`). Only the runtime-provided Env gives code this ambient authority, so code that is not handed `env` (or a derived capability) cannot obtain it. The reason is capability-based security: access to the outside world is granted by passing a capability, not by global access. I did not scrape the AmbientAuth page itself, so the reason is taken from the Env docs wording and the general capability model.

URLs:
- https://stdlib.ponylang.io/builtin-Env/

Confidence: high for the type (directly on the page); medium-high for the "why" (inferred from "root capability" wording, AmbientAuth page not read)

## P3. Order of values from Promises.join, and Promise.next signature

Answer (order): The joined array is NOT in the order the promises were given. The `Promises.join` doc says: "The order that values appear in the final array is based on when each promise is fulfilled and not the order that they are given." Fulfilling in the order p2, p3, p1 therefore gives the array `["second"; "third"; "first"]`, which is the same order as the stdlib example prints. Note that the doc's example calls `p2("second")`, `p3("third")`, `p1("first")` in that same sequence.

Answer (signature of Promise.next), from https://stdlib.ponylang.io/promises-Promise/:

```
fun tag next[B: Any #share](
  fulfill: Fulfill[A, B] iso,
  rejected: Reject[B] iso = RejectAlways[B])
: Promise[B] tag
```

- Receiver: `tag` (the method is called on a `Promise[A] tag`).
- `fulfill`: `Fulfill[A, B] iso`, no default.
- `rejected`: `Reject[B] iso`, default `RejectAlways[B]`.
- Return: `Promise[B] tag`.

URLs:
- https://stdlib.ponylang.io/promises-Promises/
- https://stdlib.ponylang.io/promises-Promise/

Confidence: high for the join ordering rule and the next signature (both quoted from the stdlib pages). The example result is derived from the doc's stated ordering rule.
