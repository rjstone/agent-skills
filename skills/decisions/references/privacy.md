# Privacy check

Using a decision model usually adds a third-party provider the user has no
agreement with. Every item sent is data leaving their control.

## Rule of thumb

- Free or very cheap models: assume the provider keeps prompts indefinitely
  and may train on them.
- Paid models: the provider may still retain or train unless the account or
  request opts out.
- Always read the current terms; the agent cannot settle this for the user.

## Reading a policy (what to summarize)

1. **Retention:** how long prompts and answers are kept, and where.
2. **Training:** whether they are used to train or improve models, and how to
   opt out.
3. **Access and sharing:** human review, subprocessors, upstream providers (a
   gateway such as OpenRouter forwards to the model's host, whose own policy
   applies).
4. **Controls:** zero-data-retention routing, region pinning, enterprise or
   no-training terms. OpenRouter shows each provider's retention and training
   tier and can restrict routing to zero-retention providers (links in
   `providers.md`).

Summarize in 2-4 plain sentences with the page link and the date you read it.

## The three confirmations

Ask the user, and wait for an explicit yes to each:

1. **The data is OK to send.** Name the kind of data (customer emails,
   invoices with bank details, public forum posts). Nothing regulated or
   confidential (personal data under privacy law, health, payment, secrets,
   material under NDA) goes out beyond what the user's rules allow.
2. **The terms are acceptable.** They read your summary of retention and
   training and accept it for this data.
3. **The responsible parties agree.** Whoever owns the data (employer,
   client, data owner) agrees, or the user is that party.

You cannot contact those parties; you inform the user and record their
answer. If any answer is no or unsure: do not send. Offer a provider with
stricter terms, sending less (only the fields the decision needs), or made-up
data for a trial (`--test-data`).

## Recording

```bash
python3 <skill>/scripts/decide.py privacy leads.decisions.json \
  --provider opencode --policy-url https://opencode.ai/legal/privacy-policy \
  --summary "Read 2026-11-23: ... (2-4 sentences)"
```

This writes `privacy.<provider>` with the date. Each provider needs its own
entry; fallbacks without one are skipped. A new or changed provider means a
new check.
