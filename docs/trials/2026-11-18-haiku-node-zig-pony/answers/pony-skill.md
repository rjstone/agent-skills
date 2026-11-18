# Pony 0.38.1 stdlib answers

## P1. Printing a line to stdout from a Main actor

Answer: call `print` on the `out` field of the `Env` passed to `Main.create`:

```pony
actor Main
  new create(env: Env) =>
    env.out.print("Hello")
```

The field is `let out: OutStream tag` on `Env`, so its declared type is `OutStream` with the `tag` reference capability.

- Documentation reference: `pony:builtin-env#let-out-outstream-tag` (Env, "Public fields": `let out: OutStream tag`, described as "Stdout"). Env itself is `class val Env`.
- Confidence: high.

## P2. Declared type of `Env.root`

Answer: `let root: (AmbientAuth val | None val)`.

Reason, per the docs: `root` is the root capability. The docs say it "Can be None for artificially constructed Env instances". `AmbientAuth` is `primitive val AmbientAuth`, described as the root capability: "When a Pony program starts, the Env passed to the Main actor contains an instance of the root capability." Ambient access to it is denied outside the builtin package, and only the runtime's Env creates it. Other packages can accept it as a parameter to implement least authority, and it is the unlimited-access token. An Env built by hand via `Env.create` may therefore have no root, hence the `None` alternative.

- Documentation reference: `pony:builtin-env#let-root-ambientauth-val-none-val`; `pony:builtin-ambientauth` (AmbientAuth type description); `pony:builtin-env` (Env.create parameter `root'`).
- The "why" paragraph is my reading of the AmbientAuth doc and the Env doc together. The docs state the facts (runtime supplies it, None for artificial Envs, capability for least authority) but do not spell out a single rationale in one sentence.
- Confidence: high for the type; medium-high for the explanation of why.

## P3. Promise join order and `Promise.next` signature

Order: the joined array holds values in fulfillment order, not input order. The Promises.join doc says: "The order that values appear in the final array is based on when each promise is fulfilled and not the order that they are given." With fulfillment order p2, p3, p1 the array is `["second"; "third"; "first"]` for the values p2="second", p3="third", p1="first" (these are the values in the doc's own example, which fulfils p2, p3, p1 in that order). Generalised: the array is the values of p2, p3, p1 in that order.

`Promise.next` full signature (from the docs):

```pony
fun tag next[B: Any #share](
  fulfill: Fulfill[A, B] iso,
  rejected: Reject[B] iso = qualify)
: Promise[B] tag
```

- Receiver: `tag`.
- `fulfill` parameter: `Fulfill[A, B] iso`.
- `rejected` parameter: `Reject[B] iso`, with default `qualify`.
- Return type: `Promise[B] tag`.
- Type parameter: `B: Any #share`.

Documentation references: `pony:promises-promises#join` (order rule and example); `pony:promises-promise#nextb-any-share` (signature).

Confidence: high.
