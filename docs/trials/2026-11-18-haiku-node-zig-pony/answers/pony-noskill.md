# Pony 0.38.1 questions (answered from memory, no tools)

## P1. Printing a line from a Main actor

Answer: Use the `env` argument of `Main.create` and its `out` field:

```pony
actor Main
  new create(env: Env) =>
    env.out.print("Hello, world")
```

The field is `env.out`. Its declared type is `OutStream`, an interface, which I believe carries the `tag` reference capability (`interface tag OutStream`). `print` is a method on it that takes a `ByteSeq`.

Confidence: medium for the call and the `print` method. Low-medium for the exact declared type and capability of `env.out`.

## P2. Declared type of `Env.root`

Answer: `let root: (AmbientAuth | None)`, a union of `AmbientAuth` and `None`.

Why: `AmbientAuth` is the root capability that grants access to ambient authority (files, network, process). The runtime creates it and hands it only to the Main actor through `Env`. The `None` branch exists so that an `Env` can be built without any authority, for example in tests or when the program is not started by the runtime. Code that needs authority must therefore match on the union or receive an `AmbientAuth` value it has been given.

Confidence: medium for the union type. Low for the exact justification wording, since I am reconstructing the reason rather than recalling a comment.

## P3. Promise join order and `Promise.next` signature

Join order: the joined array keeps the order of the input list, not the order of fulfillment. `Promises[String val].join([p1; p2; p3].values())` gives a `Promise[Array[String val] val]` whose array is `[v1; v2; v3]`, where v1, v2, v3 are the values of p1, p2, p3. Fulfilling p2, then p3, then p1 does not change this order.

Confidence: high for the order (input order), medium for the `join` return type.

`Promise.next`: my best recollection is a generic method on `Promise[A]` that takes a fulfill closure (and an optional reject closure) returning either a `B` or a `Promise[B]`, and returns a new `Promise[B]`. Roughly:

```pony
fun ref next[B: Any #share = None](
  fulfill: {(A): (B | Promise[B]) ?} val,
  reject: {(Any): (B | Promise[B]) ?} val = ...
): Promise[B]
```

The reference capabilities are the part I am least sure of: the closures are `val`, and I believe the return is `Promise[B]` with a `tag` or `ref` capability. I cannot reliably reproduce the exact signature or its default for `reject`.

Confidence: low for the full signature and the reference capabilities. Medium that `next` returns a new promise and that its callbacks take the fulfilled value.
