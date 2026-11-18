# Pony 0.38.1 answers (docshelf only)

## P1 (easy): print a line from Main, and the field's type

**Answer:** Call `env.out.print("text")` in `actor Main`'s constructor, where `env: Env` is the parameter. `Env.out` is a public field declared as `let out: OutStream tag`. Its declared type is `OutStream tag` (`tag` reference capability). `OutStream.print()` takes the line to print.

**REF:** `pony:builtin-env` (Public fields, `let out: OutStream tag`); `pony:promises-promises#join` (example uses `env.out.print(s)`); `pony:builtin-outstream#print`

**Confidence:** high

## P2 (medium): declared type of `Env.root`, and why

**Answer:** `Env.root` is declared `let root: (AmbientAuth val | None val)`. It is the root capability. `AmbientAuth` is the root capability type (`primitive val AmbientAuth`). The docs say that when a program starts, the `Env` passed to `Main` contains an instance of it. Ambient access to it is denied outside the builtin package, so other packages get only the limited capabilities they are handed. Packages can accept `AmbientAuth` as a parameter to represent unlimited access, which supports least-authority design. The `| None` branch exists because the docs say `Env` instances built artificially (via `Env.create`) can have `None` as their root.

**REF:** `pony:builtin-env` (`let root` and `new val create` parameter `root'`); `pony:builtin-ambientauth` (type description)

**Confidence:** high for the declared type; medium-high for the reason. The docs state the purpose (root capability, least-authority pattern, `None` for artificial Envs) but do not spell out the union rationale in one sentence, so that part is my reading.

## P3 (hard): join order and `Promise.next` signature

**Answer, join order:** The values appear in the order the promises are fulfilled, not the order they were given. The docs say: "The order that values appear in the final array is based on when each promise is fulfilled and not the order that they are given." Fulfilling in the order p2, p3, p1 gives the array `["second"; "third"; "first"]`, where p2 = "second", p3 = "third", p1 = "first". The docs show the join pattern in an example but do not print the output, so this result comes from the documented ordering rule, not from a run.

**Answer, `Promise.next` signature:**
```pony
fun tag next[B: Any #share](
  fulfill: Fulfill[A, B] iso,
  rejected: Reject[B] iso = qualify)
: Promise[B] tag
```
- Receiver: `tag` (the method is `fun tag`).
- `fulfill`: `Fulfill[A, B] iso`.
- `rejected`: `Reject[B] iso`, default `qualify`.
- Return: `Promise[B] tag`.
- Type parameter: `B: Any #share`.

**REF:** `pony:promises-promises#join` (ordering text and example); `pony:promises-promise#nextb-any-share` (signature)

**Confidence:** high for the `next` signature. High for the ordering, which is taken from the documented rule.
