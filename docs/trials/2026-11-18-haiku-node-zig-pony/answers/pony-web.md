# Pony (stdlib 0.38.1) - web answers

Note: stdlib.ponylang.io and docs.w3cub.com failed to resolve from this session (network allowlist), so the answers below rest on search-result snippets and mirrors, not on fetched page text. Confidence is set accordingly.

## P1. Printing a line from Main, and the field's type

**Answer:** Use `env.out.print("text")`, where `env` is the `Env` parameter of `Main.create(env: Env)`. `print` takes a `ByteSeq` and appends a newline; `write` does not. The field `Env.out` is declared as `let out: OutStream tag` (a `tag` reference capability). The concrete implementation is the `StdStream` actor, which has `be print(data: ByteSeq)`.

**Sources:**
- https://docs.w3cub.com/pony/builtin-env (search snippet only)
- https://stdlib.ponylang.io/src/builtin/std_stream/ (search snippet only)
- https://stdlib.ponylang.io/builtin-StdStream/ (search snippet only)

**Confidence:** medium. The `OutStream tag` name comes from one search snippet, and another snippet called the object `StdStream`. I could not confirm which name current 0.38.1 uses for the field type, so check `builtin/env.pony` before relying on the exact name.

## P2. Declared type of `Env.root` and why

**Answer:** `Env.root` is declared as `AmbientAuth` (no union with `None`). In the current stdlib, `class val Env` has `let root: AmbientAuth`, and the constructor takes it as a non-optional parameter. Older docs showed `(AmbientAuth val | None val)`; that was changed by ponyc PR #3962 ("Change type of Env.root to AmbientAuth"), which implemented RFC 65 in January 2022. Its capability is `val` as shown on the generated docs page (`AmbientAuth val`).

**Why:** `AmbientAuth` is the unforgeable root capability for ambient authority (object-capability design). The runtime creates it and hands it to `Main` through `Env`. Ambient access to the root capability is restricted to the builtin package and the runtime, so user code cannot fabricate it. Removing `None` means every `Env` carries a real capability, so code never has to check for a missing one.

**Sources:**
- https://stdlib.ponylang.io/builtin-Env/ (search snippet only)
- https://stdlib.ponylang.io/src/builtin/env (search snippet only)
- https://stdlib.ponylang.io/builtin-AmbientAuth/ (search snippet only)
- https://github.com/ponylang/ponyc/pull/3962 (seen via a mirror in search results)
- https://tutorial.ponylang.io/object-capabilities/derived-authority (search snippet only)

**Confidence:** medium-high on the declared type (several sources agree, plus the PR). Medium on the `val` capability detail. Medium on the rationale, which is inferred from the object-capability docs.

## P3. Join ordering and the signature of `Promise.next`

**Join ordering:** The values appear in the joined array in the order the promises are fulfilled, not the order they were passed in. Fulfilling p2, then p3, then p1 gives the array `[v2; v3; v1]`, where v1, v2, v3 are the values of p1, p2, p3. The stdlib `Promises.join` doc says: "The order that values appear in the final array is based on when each promise is fulfilled and not the order that they are given."

**`Promise.next` signature:** `fun tag next[B](fulfill, rejected = ...): Promise[B] tag`. The receiver is `tag`, and the return type is `Promise[B] tag`. The snippet did not show the full type of `fulfill` or `rejected`. My best recollection is `fulfill: {(A): B ?} val` and a `rejected` parameter `{(Any): B ?} val` with a default, but I could not verify this, so treat the parameter types as unconfirmed. A companion `flatten_next` takes a function returning `Promise[B]` and unwraps it.

**`join` signature:** Search snippets show two variants: `fun tag join(ps: Iterator[Promise[A] tag] ref): Promise[Array[A] val] tag` (on `Promise`) and `fun box join(ps: Iterator[Promise[A] tag] ref): Promise[Array[A] val] tag` (on `Promises`).

**Sources:**
- https://stdlib.ponylang.io/promises-Promises/ (search snippet only)
- https://stdlib.ponylang.io/promises-Promise/ (search snippet only)
- https://stdlib.ponylang.io/src/promises/promise (search snippet only)
- https://docs.w3cub.com/pony/promises-promise (search snippet only)

**Confidence:** Join ordering: medium-high (the doc sentence appeared in a search snippet). The `next` signature: low-medium (name and return type confirmed; parameter types unverified). The `join` capability variants: low-medium, because the snippets disagree.
