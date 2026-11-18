# Pony 0.38.1 stdlib answers (P1-P3)

Source of all answers: offline DevDocs for Pony 0.38.1, read with docshelf
(`DOCSHELF_CACHE_DIR` set to the scratchpad `dscache`). No web access used.

## P1. Printing a line from the Main actor

Answer: call `print` on the `out` field of the `Env` passed to `new create`:

```pony
actor Main
  new create(env: Env) =>
    env.out.print("Hello, world")
```

`print` is a behaviour on `OutStream`: `be print(data: (String val | Array[U8 val] val))`.
It prints the bytes and appends a newline (`write` is the variant without a newline).

Declared type of the field used: `let out: OutStream tag`
(in `Env`: `class val Env`, with `let out: OutStream tag`, "Stdout").

Documentation references:
- `pony:builtin-env` ("Public fields", `let out: OutStream tag`)
- `pony:builtin-outstream#print` (`be print(data: (String val | Array[U8 val] val))`)

Confidence: high.

## P2. Declared type of `Env.root`, and why

Answer: `let root: (AmbientAuth val | None val)`.

Why: `AmbientAuth` is the root capability. The docs say that ambient access to it
is denied outside the builtin package, and that only `Env` creates it inside the
builtin package. So the runtime can hand the root to `Main` and any package can
accept it as a least-authority parameter, but user code cannot forge one. The
`| None val` branch exists because "Can be None for artificially constructed Env
instances", i.e. an `Env` built with `Env.create(...)` (which takes
`root': (AmbientAuth val | None val)`) can have no root at all.

Documentation references:
- `pony:builtin-env` ("Public fields": `let root: (AmbientAuth val | None val)`,
  "The root capability. Can be None for artificially constructed Env instances.")
- `pony:builtin-ambientauth` (type description: root capability, denied outside
  the builtin package, only `Env` creates a Root)

Confidence: high.

## P3. Promise join order, and `Promise.next` signature

Join order: the values appear in the order the promises were fulfilled, not the
order they were given to `join`. Fulfilling p2, then p3, then p1 gives:

```
["second", "third", "first"]
```

Here p2 = "second", p3 = "third", p1 = "first". The `Promises.join` doc says: "The
order that values appear in the final array is based on when each promise is
fulfilled and not the order that they are given." The docs' own example uses the
same `join` call and the same p1/p2/p3 names, and it fulfils them in that same
order (p2, p3, p1).

Signature of `Promise.next` (declared on `actor tag Promise[A: Any #share]`):

```pony
fun tag next[B: Any #share](
  fulfill: Fulfill[A, B] iso,
  rejected: Reject[B] iso = qualify)
: Promise[B] tag
```

- Receiver: `tag` (the method is `fun tag`).
- `fulfill`: `Fulfill[A, B] iso` (iso, no default).
- `rejected`: `Reject[B] iso`, default `= qualify`.
- Return: `Promise[B] tag`.
- Type parameter: `B: Any #share`.

Documentation references:
- `pony:promises-promises` (`join`, with the ordering sentence and example)
- `pony:promises-promise` ("Public Functions": `next[B: Any #share]`, `join`)

Confidence: high for the signature and the stated ordering rule. The
join-order answer follows directly from the documented rule, and the docs' example
uses the same fulfilment order, but the docs do not print the output array for it.
