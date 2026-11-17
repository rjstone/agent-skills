<!--
Sections marked (required) always need filling in. (skills) sections are
required when the PR adds or changes a skill; delete them otherwise.
(if it applies) and (optional) sections: delete them when empty.
Rules referred to here are in AGENTS.md.
-->

## Kind (required)

<!-- Keep one. -->
- New skill: `skill/<name>`, **squash-merge**
- Skill update: `update/<name>`, **merge commit**
- Repo-level change: notes, tests, CI, tooling

## Skill and version (skills)

<!-- `<name>`: old -> new, and which AGENTS.md bump rule applies:
     major / minor (feature, or files added) / patch (fix). -->

## What changed and why (required)

<!-- A few bullets. Name any decision that also belongs in AGENTS.md. -->

## Public-repo checklist (skills)

- [ ] Generally useful, not tied to one project or person
- [ ] No machine or account details (names, hostnames, home paths, private URLs)
- [ ] No secrets of any kind, not even expired or test ones
- [ ] Quality: "Use when..." description, concise, tested with agents
- [ ] Original to this repo, with any upstream credited
- [ ] I read the whole diff, not just the safety test result

## Testing (skills)

<!-- - `python3 -m unittest discover -s tests`: N tests pass (N new)
     - `python3 scripts/ci_changed_skills.py --base main --check-versions`
     - Real data or agent trials: what, which model and effort,
       calls and characters of script output -->

## Docs touched (if it applies)

<!-- SKILL.md, references/, AGENTS.md or CLAUDE.md notes, TODO.md items
     closed, plans archived to docs/plans/ or docs/superpowers/. -->

## Follow-ups (optional)

<!-- Deferred work; add it to TODO.md too. -->
