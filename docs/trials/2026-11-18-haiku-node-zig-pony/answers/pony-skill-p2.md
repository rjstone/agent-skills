# Pony 0.38.1 stdlib answers (P1-P3)

## P1. Printing a line to stdout from a Main actor

Answer: call `print` on `env.out`, where `env` is the `Env` parameter of the Main actor's constructor:

```pony
actor Main
  new create(env: Env) =>
    env.out.print("Hello")
```

The field is `Env.out`, declared as `let out: OutStream tag` (the doc comment says "Stdout").
Declared type: `OutStream tag`.

- Documentation reference: `pony:builtin-env#let-out-outstream-tag` (Env page, "Public fields"); the Env page's `create` and `root` sections were read for context.
- Confidence: high.

## P2. Declared type of `Env.root` and why

Answer: `let root: (AmbientAuth val | None val)`.

Why (from the docs):
- `AmbientAuth` is the root capability. The docs say: "When a Pony program starts, the Env passed to the Main actor contains an instance of the root capability." Ambient access is denied outside the builtin package, so only `Env` creates it. Other packages can accept it as a least-authority token, and it represents unlimited access.
- The `None` alternative exists because `Env` instances can be built artificially (`Env.create` takes a `root'` of the same type). The field doc says: "Can be None for artificially constructed Env instances."
- `val` (AmbientAuth is a `primitive val`, and the field is `val`) lets the capability be shared freely across actors.

Note: the doc does not spell out the reasoning for the union in one sentence; the "why" above combines the AmbientAuth page with the Env field and constructor docs.

- Documentation reference: `pony:builtin-env#let-root-ambientauth-val-none-val` (Env page); `pony:builtin-ambientauth` (AmbientAuth page, "This type represents the root capability..."); `pony:builtin-env#create`.
- Confidence: high for the declared type; medium-high for the rationale.

## P3. Order of joined values and the signature of `Promise.next`

Order: the joined array is `["second", "third", "first"]`.

Reason: the join doc says "The order that values appear in the final array is based on when each promise is fulfilled and not the order that they are given." The fulfil order in the question is p2, p3, p1, so the values appear as "second", "third", "first". The Promises doc example in the docs uses the same fulfil order and prints the same sequence.

Signature of `Promise.next` (documented as `Promise[A: Any #share]`, method `next[B: Any #share]`):

```pony
fun tag next[B: Any #share](
  fulfill: Fulfill[A, B] iso,
  rejected: Reject[B] iso = qualify)
: Promise[B] tag
```

- Receiver: `tag` (the method is a `fun tag`).
- `fulfill`: `Fulfill[A, B] iso`.
- `rejected`: `Reject[B] iso`, with default value `qualify`.
- Return type: `Promise[B] tag`.

- Documentation reference: `pony:promises-promises#join` (Promises page, join example and doc); `pony:promises-promise#nextb-any-share` (Promise page, next).
- Confidence: high.

## Method

Commands used: `docshelf.py --help`, `list`, `search` (Env, Main, Promises join, Promise next), `show` on the entries above, `show --grep=root`, `show --full` on Env and AmbientAuth. Cache: `DOCSHELF_CACHE_DIR` set to the scratchpad `dscache` folder. No web search or fetch used.
