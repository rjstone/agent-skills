# Zig 0.17.1 answers

## Z1. @divFloor(-5, 3) and @divTrunc(-5, 3)

- `@divFloor(-5, 3)` evaluates to **-2** (floored division rounds toward negative infinity).
- `@divTrunc(-5, 3)` evaluates to **-1** (truncated division rounds toward zero).

Reference: docshelf `zig:index#divFloor` and `zig:index#divTrunc` (Zig Language Reference, Builtin Functions). The docs state `@divFloor(-5, 3) == -2` and `@divTrunc(-5, 3) == -1`.

Confidence: high

## Z2. Jumping from `continue` to another switch prong

Label the switch and use a labeled `continue` with an operand:

```zig
sw: switch (value) {
    5 => continue :sw 4,
    // ...
}
```

The `continue` must:

- target a labeled switch (`continue :label`), because an unlabeled `continue` cannot target a switch;
- include an **operand**. The docs say "A continue targeting a switch must have an operand." The operand replaces the switch value, and execution jumps to the prong that matches it, as if the switch were executed again with that value.

A `continue` may also appear several times within one prong.

Reference: docshelf `zig:index#Labeled-switch` (Zig Language Reference, Labeled switch).

Confidence: high

## Z3. Constructing the integer type u18 at comptime

The builtin is `@Int`, with this signature:

```zig
@Int(comptime signedness: std.lang.Signedness, comptime bits: u16) type
```

It returns an integer type with the given signedness and bit width. Example from the docs: `@Int(.unsigned, 18)` returns `u18`.

Reference: docshelf `zig:index#Int` (Zig Language Reference, Builtin Functions: `@Int`).

Confidence: high for the signature and example as given in the installed Zig 0.17.1 docs. The docs do not say whether `std.lang.Signedness` values are written `.unsigned` or `.signed`; the example shows `.unsigned`.
