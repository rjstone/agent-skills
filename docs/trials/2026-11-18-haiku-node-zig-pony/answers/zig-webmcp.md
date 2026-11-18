Service: Firecrawl (chosen for search plus scrape of the official Zig docs in one service; firecrawl_search and firecrawl_scrape cover both steps)

Z1. `@divFloor(-5, 3)` is -2 and `@divTrunc(-5, 3)` is -1.
- @divTrunc: the Zig 0.17.1 reference states `@divTrunc(-5, 3) == -1` (rounds toward zero).
- @divFloor: the reference says it rounds toward negative infinity; -5/3 = -1.67, floored to -2. The exact example line was not retrieved from the page (scrape truncated), so the -2 value rests on the rounding rule plus the math.
- URLs: https://ziglang.org/documentation/0.17.1/ (scraped; @divTrunc example confirmed), https://ziglang.org/documentation/0.17.1/#divFloor (scrape truncated, did not reach the section)
- Confidence: @divTrunc high; @divFloor medium-high.

Z2. Use a labeled switch: put a label on the switch (`sw: switch (...) { ... }`) and write `continue :sw <new value>` inside a prong. The continue must name the switch's label and include the new operand (the value the switch is re-dispatched on). It can appear several times in one prong. `break :sw` exits the labeled switch.
- Example from the reference: `sw: switch (@as(i32, 5)) { 5 => continue :sw 4, ... }`.
- The excerpt says "A `continue` targeting a switch must have an [expression]", so the operand is required; this matches the example.
- URLs: https://ziglang.org/documentation/master/ (search excerpt with the labeled switch examples; the 0.17.1 page was not reached for this section), https://ziggit.dev/t/how-to-break-a-switch-body/1722 (background discussion, not used for the answer)
- Confidence: medium. The labeled-switch syntax is consistent across sources, but the search source was the master docs, not the 0.17.1 page.

Z3. Use `@Int(comptime signedness: std.lang.Signedness, comptime bits: u16) type`. So u18 is `@Int(.unsigned, 18)`. `std.lang.Signedness` has values `.signed` and `.unsigned`.
- URLs: https://ziglang.org/documentation/master/ (search excerpt shows the signature under Builtin Functions; this was master, not confirmed on the 0.17.1 page), https://github.com/ziglang/zig/issues/6697 (background on the older std.meta.Int signedness proposal)
- Confidence: medium. The signature came from the search excerpt of the master docs; the 0.17.1 page was not verified for this builtin.
