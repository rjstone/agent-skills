---
name: concept-parable
description: Use when the user wants a concept, subject or domain explained, taught or illustrated through a story, parable, fable, allegory or extended metaphor rather than directly - "explain X as a story", "write a fable about Y", "teach Z through a parable", "illustrate this indirectly" - even if the words parable or fable never appear. Creative writing only; not for diagrams or code.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Concept Parable

Given a concept, subject, or domain, write a short fable that dramatizes the concept's *mechanics*
indirectly through story, keeps the concept's identity hidden until a late reveal, and then explains
— concisely — how each part of the story stood for a part of the concept.

The value of a good concept-parable is that a reader meets the *shape* of an idea before they meet
its name, so the name later lands on a structure they already understand. That only works if the
structure in the story is truly the concept's structure. Most of this skill is about getting that
right.

## If the subject is a broad domain

Pick one specific, interesting concept from it. Avoid the single most commonly-cited concept in that
domain unless it is genuinely the best fit — the obvious pick is usually the one the reader has
already met head-on. When choosing among several candidates with no clear winner, vary your choice
rather than always defaulting to the same instinct; pseudo-random selection is fine if it helps you
break a tie.

## The core tension — resolve it before you start

"Illustrate the mechanics *fully*" and "keep the concept *hidden*" sound contradictory. They are not,
once you separate **structure** from **identity**:

- Render the **structure** faithfully and completely — the parts, how they relate, and the
  conditions under which the relation holds — so that a reader could reverse-engineer the concept
  from the story alone.
- Hide only the **identity** — the concept's name and its domain's vocabulary. Use no technical
  labels, jargon, or telltale terms until the reveal.

You are hiding the *label on the box*, never the *contents of the box*.

## Before writing: map three kinds of parts

Forced, creaky parables almost always come from mapping only nouns — thing-to-thing — and neglecting
the rest. A concept has three kinds of parts. Enumerate all three, then invent one story stand-in for
each:

1. **Entities** — the things involved. These become characters and objects. This part is easy and
   rarely where parables fail.
2. **Relations and operations** — what acts on what, what transforms into what, what depends on what.
   These become the events and actions of the plot.
3. **The governing condition** — the constraint under which the whole thing holds: the right angle,
   the convergence requirement, the conserved quantity, the maintained invariant, the assumption that
   licenses the inference. This is usually the actual *point* of the concept, and it is the single
   easiest thing to accidentally render as scenery.

Aim for roughly one story-element per real-element — a clean, near-bijective mapping with no orphans
and no decoration. Prefer a few correspondences that carry weight over an exhaustive set that turns
the story into a puzzle.

## The load-bearing check

Before drafting, ask one question about the governing condition: **does it do real work in the plot?**

If the story would read the same with the constraint removed or violated, the constraint is
decorative — and the parable will feel forced, because the concept's heart is missing while its
surface is present. Rebuild so that when the constraint is *absent*, the story visibly fails. That
failure is frequently the most illuminating beat you can offer, because it shows the reader what the
constraint is *for*.

## Tone and shape

- Fable-like and legible. The story should be *easier* to parse than the concept, never a dense
  allegory that is harder to decode than the thing it explains.
- Keep the subject hidden or ambiguous for most of the story. No winks, no giveaway vocabulary.
- A few paragraphs. It must work as a story first — satisfying even to a reader who never decodes it.
- The strongest reveals are a **recontextualizing turn**: a final image or line that makes the reader
  see the whole story *was* the concept all along, rather than a label bolted onto the end. Reach for
  that when the material allows; don't force it if a plainer reveal serves better.

## After the story: the mapping

Stop the story, then write a separate explanation:

- Name the concept plainly.
- Map each story element to what it stood for — entities, relations, and *especially* the governing
  condition. Make the condition's role explicit; it is the part the reader most needs named.
- Keep it no longer than necessary to communicate the mapping. This is a key, not an essay.
- Optional closing beat: one honest line on where the analogy simplifies or breaks down. This builds
  trust and marks the boundary of the metaphor so the reader knows how far to carry it.

## Silent self-check before shipping

Verify these in your reasoning, not on the page:

- Could a reader who does not know the concept reconstruct its mechanics from the story alone?
- Does every essential part appear — entities, relations, and the governing condition?
- Does the constraint do load-bearing work, or is it scenery?
- Does it read as a story first, not a cipher?
- Is the reveal genuinely late, and ideally a turn rather than a tacked-on label?

If any answer is no, fix it before returning the parable.

## Domain notes: what tends to go invisible

Different domains hide their load-bearer in different places. Use these hints to find the part most at
risk of becoming scenery, and the framing that tends to resist forcing. Extend this table as new
domains come up.

| Domain | What tends to go invisible | Framing that resists forcing |
|---|---|---|
| Mathematics | the governing condition (a right angle, a convergence or invertibility assumption) | a physical action or process, not a static container of "stuff" |
| Physics / chemistry | the *mechanism* of change (conserved quantities are the easy part) | a process unfolding over time |
| Biology / evolution | the selective pressure — the filter — not the surviving trait | many trials run against an environment that filters them |
| Economics / game theory | incentives and information asymmetry (not the payoff numbers) | agents deciding under what they can and cannot see |
| CS / algorithms | the invariant preserved across every step | a repeated routine bound by one rule it must never break |
| Statistics | the assumption that licenses the inference | what goes wrong the moment that assumption quietly fails |

## A worked contrast — why the constraint carries the parable

Take **negative feedback** (a system that self-corrects toward a set point).

- **Forced:** a gardener waters the plants each day. Watering illustrates "an action," but nothing in
  the story ties the *size* of the action to *how far things have drifted* — the story reads
  identically whether or not any feedback exists. The concept's heart is missing; only its surface
  (someone doing something regularly) is present.
- **Faithful:** the response *scales with the deviation* — a small drift brings a small correction, a
  large drift a large one — and when that proportionality is broken (the corrector overreacts, or
  reacts late), the system visibly overshoots and oscillates. Now the governing relation is doing the
  work, the failure mode teaches what the constraint is for, and a reader could recover "negative
  feedback" from the mechanics without ever being told the name.

The difference between the two is not vocabulary or polish. It is whether the governing condition was
mapped and made load-bearing, or left as scenery.

## Credits

Originally inspired by an idea expressed by Amanda Askell of Anthropic in a video interview.
