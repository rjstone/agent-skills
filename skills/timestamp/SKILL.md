---
name: timestamp
description: Use when the user types /timestamp (alone or with start, end, both, on or off), asks which timestamp mode is active, or asks to turn time checks on, off or to another time zone; also when a turn that should carry a timestamp is missing one, or a printed timestamp looks made up rather than read from a tool.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Timestamp

An in-session mode that prints the current time, with the delta since the last printed
time, at the start and/or end of each turn. Off until the user turns it on. There is no
storage: the current mode and time zone are whatever the most recent `/timestamp`
command and time-zone line in *this* conversation set (scan back for them).

## The command

`/timestamp <arg>` arrives in the message text or as a slash command with arguments.
Arguments are case-insensitive:

| Argument | Mode |
|---|---|
| `start` / `end` | that one |
| `both`, `on`, `enable` | `both` |
| `off`, `none`, `disable` | `off` |
| *(none)* | `end` |

Reply on that turn, in this order:

1. `Timestamps <enabled|disabled> at <start|end|start and end> of turn.` ("disabled" only
   for `off`, naming the mode being turned off; "start and end" for `both`).
2. Only when the mode goes from `off` to on, the time-zone line (below).
3. The new mode's checks for this same turn: a start check now if it includes `start`, an
   end check at the close if it includes `end`. `off` means no checks on that turn.

Asked which mode is active? Say it; don't run a time check for that.

## Time zone

Chosen once, when the mode goes from `off` to on:

- Known from the user's saved preferences, instructions or this conversation:
  `Using your preferred time zone <TZ>. To change, just request a different time zone.`
- Otherwise UTC:
  `Using default UTC for timestamp time zone. To change, just request a different time zone.`

The user can switch at any time in plain words ("use Pacific time"): acknowledge in one
line and use the new zone from then on.

## Reading the time

Never print a time you did not just read from a tool. Sources, per conversation:

1. A dedicated time tool, if your tool list has one (e.g. `user_time_v0` in the Claude
   mobile app). Try it once; if it fails or is absent, don't try it again this session.
2. Any shell or code-execution tool (`Bash`, `bash_tool`, a terminal), with the zone as an
   IANA name: `TZ=America/Los_Angeles date '+%Y-%m-%d %H:%M:%S %Z %s'` (the last field is
   epoch seconds, for the delta).

- Compute deltas from epoch seconds, not by subtracting clock strings.
- Never use the date in your system prompt or context: it has no time of day and may be
  in another zone.
- Write the time into your reply text; tool output is often hidden from the user.
- No source available: print `[no time source available this turn]`.

## Format and placement

```
[2026-08-01 14:32:07 PDT, +00:03:12]
[2026-08-01 14:32:07 PDT, first check]
```

- Own line, square brackets, zone label always shown.
- Delta `+HH:MM:SS` since the last printed timestamp; past 24 hours `+Nd HH:MM:SS`.
- `first check` instead of a delta for the conversation's first one.
- `start`: the very first thing in the turn, before any other text or tool call (on the
  `/timestamp` turn itself, right after lines 1-2 above).
- `end`: the very last thing, after all other content and tool calls.
- `both`: both; the end check's delta is measured from the start check.

## Self-check

If the mode is on and the previous turn is missing a check it should have had, or shows a
time that wasn't read from a tool, re-read this skill and follow it strictly from now on.
