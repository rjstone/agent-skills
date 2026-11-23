# Advanced patterns

A few common patterns beyond the basics. For everything else, start from
TypeSafe's docs index, https://docs.typesafe.ai/llms.txt (every page with a
one-line summary and its plain-text `.md` link), then read Patterns
(https://docs.typesafe.ai/patterns.md), Cookbooks
(https://docs.typesafe.ai/cookbooks.md) or structured questions
(https://docs.typesafe.ai/primitives/advanced.md). They apply to any System
One model.

- **Screen with a yes/no first.** Ask one cheap yes/no ("is this a real
  lead at all?") and run the costly step (more questions, a large model) only
  on a clear yes. https://docs.typesafe.ai/patterns/noul-screen.md
- **Companion yes/no for choices.** A choice always picks something. Pair it
  with "does any option fit?" so your code can tell "none of these". 
  https://docs.typesafe.ai/patterns/companion-noul.md
- **Route by confidence, and by probability per action.** Score says what,
  confidence says whether to act; give riskier actions (auto-hide, auto-pay)
  a higher probability bar than cheap ones (flag for review).
  https://docs.typesafe.ai/patterns/confidence-routing.md ,
  https://docs.typesafe.ai/patterns/probability-routing.md
- **Composite scoring.** Break a fuzzy judgment into several small questions
  and combine them with weights in your own code, which you can tune without
  re-asking. https://docs.typesafe.ai/patterns/composite-scoring.md
- **Speculative fan-out.** Extra questions in the same request are nearly
  free; ask the ones a later step might need now.
  https://docs.typesafe.ai/patterns/fan-out.md
- **Large option lists (hundreds of codes).** Walk the tree: a first choice
  picks the group (expenses, assets, ...), with each option's value being
  that group's subtree (its codes, trimmed to direct children and a few
  leaves if large) so the model sees what lives under a branch; then a second
  choice per group picks the code within it. Route low confidence at either
  step to review; when the top two groups are close, try both.
  https://docs.typesafe.ai/primitives/advanced.md (Walking a taxonomy).
  `decide.py` doesn't chain steps (by design; your own code or the agent
  does): run a setup for the group question, split its output by the chosen
  group, then run one setup per group for the code. See
  https://docs.typesafe.ai/cookbooks/hierarchical_classification.md ,
  https://docs.typesafe.ai/cookbooks/classification_using_confidence.md and
  https://docs.typesafe.ai/cookbooks/infinite_cardinality_choice.md

## Images (not in this version)

System One models such as Jev can read images in `state`, in instructions
and as criteria, and `box` questions locate things in an image. `decide.py`
sends text only. See https://docs.typesafe.ai/images.md and
https://docs.typesafe.ai/primitives/box.md
