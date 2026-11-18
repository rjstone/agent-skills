# Zig 0.17.1 answers (p2)

Docs source: docshelf docvol `zig` (Zig 0.17.1, Zig Language Reference pages), read with `docshelf search`, `fts`, and `show`.

## Z1. `@divFloor(-5, 3)` and `@divTrunc(-5, 3)`

- `@divFloor(-5, 3)` = **-2** (floored division, rounds toward negative infinity).
- `@divTrunc(-5, 3)` = **-1** (truncated division, rounds toward zero).

Reference: Zig Language Reference, Builtin Functions: `@divFloor` and `@divTrunc`. The docs list exactly `@divFloor(-5, 3) == -2` and `@divTrunc(-5, 3) == -1`.

Confidence: **high**.

## Z2. `continue` jumping to another prong of a `switch`

The switch must be labeled (for example `sw: switch (...) { ... }`). A `continue` that targets it is written `continue :label operand`, and it **must have an operand**. Executing it jumps to the prong that matches the operand, as if the switch had been executed again with that operand as the switch value. A single prong may contain several `continue` statements.

Example from the docs:

```zig
sw: switch (@as(i32, 5)) {
    5 => continue :sw 4,
    2...4 => |v| {
        if (v > 3) {
            continue :sw 2;
        } else if (v == 3) {
            break :sw;
        }
        continue :sw 1;
    },
    1 => return,
    else => unreachable,
}
```

So the `continue` must include: the **label** of the switch, and a **new operand value** for the switch expression (no bare `continue` is allowed for a switch).

Reference: Zig Language Reference, "Labeled switch" section (`zig:index#Labeled-switch`).

Confidence: **high**.

## Z3. Constructing `u18` at comptime from signedness and bit width

Builtin signature (from the 0.17.1 docs):

```zig
@Int(comptime signedness: std.lang.Signedness, comptime bits: u16) type
```

It returns an integer type with the given signedness and bit width. The docs example: `@Int(.unsigned, 18)` returns the type `u18`. So `u18` is written `@Int(.unsigned, 18)`. For a signed type, use `.signed`.

Reference: Zig Language Reference, Builtin Functions: `@Int` (`zig:index#Int`).

Confidence: **high** for the signature and example as documented. The `std.lang.Signedness` enum spelling is taken from the signature in the docs; I did not check its definition in the docs separately.
