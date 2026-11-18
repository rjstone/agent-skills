# Zig 0.17.1 answers (docshelf only)

## Z1 (easy): @divFloor(-5, 3) and @divTrunc(-5, 3)

**Answer:** `@divFloor(-5, 3)` is `-2` (rounds toward negative infinity). `@divTrunc(-5, 3)` is `-1` (rounds toward zero).

- REF: `zig:index#divFloor` and `zig:index#divTrunc` (Zig Language Reference, Builtin Functions)
- Confidence: high (both examples are stated verbatim in the reference)

## Z2 (medium): continue into another switch prong

**Answer:** Label the switch (`sw: switch (...) { ... }`), then use `continue :sw <operand>` from inside a prong. The `continue` jumps to the prong matching the operand, as if the switch were executed again with that operand replacing the switch value. The operand is required: a `continue` targeting a switch must have one. A `continue` may appear several times within one prong, and `break :sw` can exit the switch (optionally with a value).

Example from the reference:
```zig
sw: switch (@as(i32, 5)) {
    5 => continue :sw 4,
    2...4 => |v| { if (v > 3) continue :sw 2; ... continue :sw 1; },
    1 => return,
    else => unreachable,
}
```

- REF: `zig:index#Labeled-switch` (Language Reference, Labeled switch)
- Confidence: high

## Z3 (hard): constructing u18 at comptime

**Answer:** Use the `@Int` builtin:

```zig
@Int(comptime signedness: std.lang.Signedness, comptime bits: u16) type
```

Example from the reference: `@Int(.unsigned, 18)` returns the type `u18`. The signedness argument is an enum literal of `std.lang.Signedness` (`.unsigned` or `.signed`), and `bits` is a `u16`.

- REF: `zig:index#Int` (Language Reference, Builtin Functions: @Int)
- Confidence: medium-high. The signature and example come directly from the offline reference; I did not check the `std.lang.Signedness` declaration itself, and the `u16` parameter type is as the reference states it.
