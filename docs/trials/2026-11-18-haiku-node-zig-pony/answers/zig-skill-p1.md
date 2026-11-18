# Zig 0.17.1 answers (skill p1)

Source for all three: the Zig 0.17.1 offline docs (docvol `zig`, page "Zig Language Reference"), read with docshelf. No web search or fetch was used.

## Z1. `@divFloor(-5, 3)` and `@divTrunc(-5, 3)`

**Answer:**
- `@divFloor(-5, 3)` == **-2** (floored division, rounds toward negative infinity)
- `@divTrunc(-5, 3)` == **-1** (truncated division, rounds toward zero)

**Documentation reference:** `zig:index#divFloor` and `zig:index#divTrunc` (Builtin Functions). The docs list the same examples: `@divFloor(-5, 3) == -2` and `@divTrunc(-5, 3) == -1`.

**Confidence:** high

## Z2. Making a `continue` jump to another prong of a `switch`

**Answer:** Label the switch (`sw: switch (value) { ... }`), then use `continue :sw <operand>`. The `continue` jumps to the prong that matches the operand, as if the switch were executed again with that operand as its value. A `continue` that targets a switch **must have an operand**. A single prong can contain several `continue :sw` statements, for example inside an `if`. `break :sw` is also allowed and exits the switch.

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

**Documentation reference:** `zig:index#Labeled-switch` (Labeled switch section of the Zig Language Reference). The docs also give an equivalent `while (true)` loop form.

**Confidence:** high

## Z3. Constructing the integer type `u18` at comptime

**Answer:** Use the builtin `@Int`. Its signature is:

```
@Int(comptime signedness: std.lang.Signedness, comptime bits: u16) type
```

Example from the docs: `@Int(.unsigned, 18)` returns the type `u18`.

**Documentation reference:** `zig:index#Int` (Builtin Functions: `@Int`).

**Confidence:** high for the signature and example as the 0.17.1 docs state them. I did not compile the example.
