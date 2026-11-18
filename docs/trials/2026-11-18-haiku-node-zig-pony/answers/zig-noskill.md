# Zig 0.17.1 answers (from memory, no tools)

## Z1. `@divFloor(-5, 3)` and `@divTrunc(-5, 3)`

- `@divFloor(-5, 3)` = **-2** (floor of -1.67 rounds toward negative infinity).
- `@divTrunc(-5, 3)` = **-1** (truncation rounds toward zero).

Confidence: **high**

## Z2. `continue` to another prong of a `switch`

Use a labeled switch. Put a label before the `switch`, then write `continue :label value` inside a prong. The value is the operand of the new switch, so the operand must be comptime-known and must match one of the prongs. The `continue` must sit inside that switch, and it must name the label and give the new operand. Without the new operand value, the `continue` is not valid.

Example shape:

```zig
sw: switch (state) {
    .a => continue :sw .b,
    .b => {},
}
```

Confidence: **medium** (labeled switch with `continue :label` was introduced around 0.14; I recall the operand-must-be-comptime-known rule but am not certain of every detail for 0.17.1).

## Z3. Constructing `u18` at comptime

Use the builtin `@Int` (it replaced `@Type(.{ .int = ... })` in 0.14):

```zig
@Int(comptime signedness: std.builtin.Signedness, comptime bits: u16) type
```

For `u18`: `@Int(.unsigned, 18)`.

Confidence: **medium** for the 0.14 signature. I am not certain it is unchanged in 0.17.1, and I am unsure of the exact integer type of `bits` (I wrote `u16`, which may differ).
