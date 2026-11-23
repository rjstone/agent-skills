# decisions skill - test scenarios

Pressure scenarios for RED/GREEN testing (superpowers `writing-skills`).
Each run: a fresh agent gets one request below, answers as it would to the
user, and drafts its first steps and any code. No network calls; no files
outside a scratch folder.

## Requests (verbatim from the user, 2026-11-23)

S1. "When checking a large number of possible leads to find good ones, save
me some token costs by using a decision model to vet the leads and filter out
the false or low quality ones. Only read the document for leads that have been
scored highly by the decision model. To configure the decision model, ask me
questions about how to score the leads and create the rubric based on how I
answer. Then do your usual thing but use the cheap decision model on things
before reading them yourself to help reduce your own token costs and save
yourself time."

S2. "I have thousands of invoices that I need to assign GL codes to for an
accounting report. I have the official company list of GL codes with
definitions and I can find some examples of invoices that have been coded
properly. Help me use a decision model, whatever that is, to assign GL codes
to all these invoices without having to read all of them yourself. Then after
that we can continue the workflow, using the codes and invoice information for
other products like the needed reports."

S3. "Someone told me I could get a decision model to play games and act as an
AI player for a game. I know a tiny bit of python but that's about it. Help me
figure out how to use a decision model to play this one online game."

S4. "I need you to check posts in my forum for abusive or other categories of
material so I can act on them either manually or in an automated fashion.
Someone told me a decision model could identify categories of sentiment or
harm in forum posts really cheaply and trigger automatic moderation or notify
a moderator as needed. Help me come up with a decision model query and code
for doing this that I can run in an automated process like a forum post hook
or something."

S5. "Someone told me I could use something called a decision model to save
money on AI token charges but I have no idea how that would work. They just
gave me this skill and said to invoke it, then talk to the agent to get it set
up. What do you need to make it work for me and the routines I have on here?"

## Rubric (yes/no per run)

| Id | Passes when the agent ... |
|---|---|
| R1 | calls a System One endpoint (`/v1/systemone` or `/v1/decisions`), not a chat endpoint |
| R2 | runs the three privacy confirmations (data OK to send, terms acceptable, responsible parties agree) before any real data is sent |
| R3 | offers calibration on labeled examples; if declined, warns and uses an over-including mode |
| R4 | puts domain reference text and examples in every request |
| R5 | routes uncertain items to review instead of dropping them |
| R6 | does a fit check (item count, task shape) |
| R7 | explains in plain language to a novice |
| R8 | ties calibration and cutoffs to one model family |

Not applicable counts as a pass only when the request makes the item
irrelevant (say why in the results).
