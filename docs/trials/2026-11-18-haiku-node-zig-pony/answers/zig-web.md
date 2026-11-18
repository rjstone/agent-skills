# Zig 0.17.1 web answers

Note: ziglang.org and codeberg.org did not resolve from this session, so the official 0.17.1 langref and release notes could not be fetched directly. Answers below rely on search-result excerpts and on well-known language semantics. Confidence reflects that.

## Z1. `@divFloor(-5, 3)` and `@divTrunc(-5, 3)`

- `@divFloor(-5, 3)` = **-2** (floor rounds toward negative infinity; -5/3 = -1.67 floors to -2)
- `@divTrunc(-5, 3)` = **-1** (truncation rounds toward zero)

URLs used:
- https://git.jakstys.lt/motiejus/zig/src/commit/7261cd19b78367d78f758f7ade370efbc3e25237/doc/langref.md (langref mirror, older commit; shows @divTrunc/@divFloor exist)
- https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2026/p4259r0 (names Zig's floor division as @divFloor and @divCeil)

Confidence: **high** for the numeric values (math and the documented rounding modes). **medium** that the 0.17.1 builtins behave as stated, since no 0.17.1 langref text was read.

## Z2. `continue` to another prong of a labeled `switch`

Label the switch, then from inside a prong use `continue :label operand`. The `continue` jumps to the prong matching the operand, as if the switch were executed again with the operand replacing the switch value. The `continue` must include an operand (a `continue` that targets a switch with no operand is a compile error). The construct is semantically equivalent to a loop.

Example shape:

```zig
sw: switch (state) {
    .a => continue :sw .b,
    .b => return,
}
```

URLs used:
- https://lists.puremagic.com/pipermail/dip.ideas/2025-July/001543.html (discussion of `continue` in labeled switch)
- https://ziggit.dev/t/labeled-switch-glitch/10745
- https://git.medv.io/zig/commit/cf691543323be9bb663aac2d19f62412435a4d39.html (labeled switch commit, excerpt only)

Confidence: **medium**. The operand requirement and the `continue :label` syntax are supported by the search excerpts. The exact langref wording was not read, and the example is my own illustration.

## Z3. Constructing `u18` at comptime from signedness and bits

In Zig 0.16 the `@Type` builtin was removed and replaced by per-kind builtins. The integer one is:

```
@Int(signedness, bits) type
```

The release notes example says `@Type(.{ .int = .{ .signedness = .unsigned, .bits = 10 } })` is equivalent to `@Int(.unsigned, 10)`. So `u18` is `@Int(.unsigned, 18)`.

Parameter types as written in the source (`comptime signedness: std.builtin.Signedness`, `comptime bits: u16`) are from memory and were not confirmed. The `bits` field of `std.builtin.Type.Int` is `u16`, per a 2022 commit excerpt.

URLs used:
- https://ziglang.org/download/0.16.0/release-notes.html (found via search; full text not fetched, the `@Int` example comes from the search excerpt)
- https://ziglang.org/download/0.17.0/release-notes.html (found via search; not fetched, so no 0.17 change to `@Int` is confirmed)
- https://git.jakstys.lt/motiejus/zig/commit/7d6be1e23d8a65e8d6e8b8745024a4641e71523e/ (enum-literal signedness example)

Confidence: **medium** that `@Int(signedness, bits)` is the 0.16/0.17 builtin and `@Int(.unsigned, 18)` yields `u18`. **low** for the exact parameter type annotations.
