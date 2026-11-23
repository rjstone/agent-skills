# Advanced patterns

A few common patterns beyond the basics. For everything else, read TypeSafe's
Patterns (https://docs.typesafe.ai/patterns.md) and Cookbooks
(https://docs.typesafe.ai/cookbooks.md); they apply to any System One model.

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
- **Large option lists (hundreds of codes).** Two steps: a first setup picks
  the group (expenses, assets, ...), then a second setup per group picks the
  code within it; route low confidence at either step to review. `decide.py`
  has no chaining in this version: run the first setup, split the output by
  group, run the second. See
  https://docs.typesafe.ai/cookbooks/hierarchical_classification.md ,
  https://docs.typesafe.ai/cookbooks/classification_using_confidence.md and
  https://docs.typesafe.ai/cookbooks/infinite_cardinality_choice.md

## Images (not in this version)

System One models such as Jev can read images in `state`, in instructions
and as criteria, and `box` questions locate things in an image. `decide.py`
v0.1 sends text only. See https://docs.typesafe.ai/images.md and
https://docs.typesafe.ai/primitives/box.md
