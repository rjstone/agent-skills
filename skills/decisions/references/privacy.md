# Privacy check

Using a decision model usually adds a third-party provider the user has no
agreement with. Every item sent is data leaving their control.

## Rule of thumb

- Free or very cheap models: assume the provider keeps prompts indefinitely
  and may train on them.
- Paid models: the provider may still retain or train unless the account or
  request opts out.
- Always read the current terms; the agent cannot settle this for the user.

## Pointing the user to the policy

The user reads the provider's written data-handling policy themselves, at
its source: it is the only binding source of truth. Your job is to find the
provider's own policy page and give the user the link. Do not replay the
page or offer a summary in place of it: an agent's summary can be wrong or
misleading. Tell the user which parts to look for:

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

A short summary is allowed only next to the link and only with this warning
first: "This summary may be incomplete or wrong. The provider's written
policy is the only binding source, and you must read it yourself." Suggest
the user contact the provider to confirm anything that seems uncertain.

## The three confirmations

Ask the user, and wait for an explicit yes to each:

1. **The data is OK to send.** Name the kind of data (customer emails,
   invoices with bank details, public forum posts). Nothing regulated or
   confidential (personal data under privacy law, health, payment, secrets,
   material under NDA) goes out beyond what the user's rules allow.
2. **They read the policy at its source and accept it.** They read the
   provider's current written policy themselves (not only something
   filtered through you) and accept it for this data. Anything uncertain:
   they ask the provider first.
3. **The responsible party agrees.** Whoever is liable and principally
   responsible for decisions regarding proper handling of the data under
   applicable laws (employer, client, data controller) agrees, or the user
   is that party.

You cannot contact those parties; you inform the user and record their
answer. If any answer is no or unsure: do not send. Offer a provider with
stricter terms, sending less (only the fields the decision needs), or made-up
data for a trial (`--test-data`).

## Recording

```bash
python3 <skill>/scripts/decide.py privacy leads.decisions.json \
  --provider opencode --policy-url https://opencode.ai/legal/privacy-policy \
  --summary "User read the policy at its source 2026-11-23; accepts it for lead text; is the data owner"
```

This writes `privacy.<provider>` with the date and the provider's endpoint.
Each provider needs its own entry; fallbacks without one are skipped. A new
provider, or a provider whose endpoint changed (for example through the
setup's `providers` block), means a new check: the script refuses until then.

## Keeping it current

Policies change. A confirmation is for the policy as it was on its date.
When a setup is reused, show the user each confirmation's date and link.
`run`, `ask` and `calibrate` warn when a confirmation is older than 90 days;
then, or whenever the provider's page shows a newer update, the user re-reads
the policy at its source and confirms again, and you record it again.
