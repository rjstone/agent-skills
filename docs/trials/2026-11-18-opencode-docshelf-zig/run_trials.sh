#!/usr/bin/env bash
# Run the docshelf Zig trial in opencode, one isolated home per model.
#
#   run_trials.sh PROVIDER/MODEL [PROVIDER/MODEL ...]
#
# Adapted from the harness of an earlier dash-docset opencode trial (kept
# outside this repo). Each model gets
# its own HOME whose only skill is a link to this repo's docshelf, and whose
# default docshelf cache (~/.cache/docshelf) holds only the Zig docvol. The
# prompt never names the skill: loading it from its description is part of
# the test. Models run in parallel, one run each.
#
# Environment:
#   SRC_CACHE  a docshelf cache that holds devdocs/zig (Zig 0.17.1) (required)
#   OUT        output folder (default: a new temporary folder, printed at start)
#   TIMEOUT    seconds per run (default 600)
#   Provider key variables (OPENCODE_API_KEY, OPENROUTER_API_KEY,
#   NOUS_API_KEY, REFLECTION_API_KEY): unset ones get a placeholder, which is
#   right when an egress proxy injects the real key.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
SKILL="$REPO/skills/docshelf"
[ $# -gt 0 ] || { echo "usage: run_trials.sh PROVIDER/MODEL..." >&2; exit 2; }
SRC_CACHE="$(cd "${SRC_CACHE:?set SRC_CACHE to a docshelf cache with devdocs/zig}" && pwd)" || exit 2
[ -d "$SRC_CACHE/devdocs/zig" ] || { echo "no devdocs/zig in $SRC_CACHE" >&2; exit 2; }
OUT="${OUT:-$(mktemp -d)}"
TIMEOUT="${TIMEOUT:-600}"
mkdir -p "$OUT"
echo "output: $OUT"
for v in OPENCODE_API_KEY OPENROUTER_API_KEY NOUS_API_KEY REFLECTION_API_KEY; do
  [ -n "${!v:-}" ] || export "$v=proxy-injected"
done

PROMPT="Using the offline Zig 0.17.1 documentation available on this machine, answer these questions. Quote the documentation and give the reference you found each answer in.
(1) What do @divFloor(-5, 3) and @divTrunc(-5, 3) evaluate to?
(2) How do you make a continue statement jump to another prong of a switch in Zig, and what must such a continue include?
(3) In Zig 0.17.1, how do you construct the integer type u18 at comptime from a signedness and a bit width? Give the builtin's exact signature."

one_model() {
  local model="$1" slug B s e
  slug=$(echo "$model" | tr '/:' '__')
  B="$OUT/$slug"
  rm -rf "$B"
  mkdir -p "$B/h/.claude/skills" "$B/h/.cache/docshelf/devdocs" "$B/xdgconf/opencode" \
           "$B/xdgdata" "$B/proj" "$B/out"
  ln -s "$SKILL" "$B/h/.claude/skills/docshelf"
  cp -r "$SRC_CACHE/devdocs/zig" "$B/h/.cache/docshelf/devdocs/"
  [ -f "$SRC_CACHE/devdocs/docs.json" ] && cp "$SRC_CACHE/devdocs/docs.json" "$B/h/.cache/docshelf/devdocs/"
  cp "$HERE/opencode.json" "$B/xdgconf/opencode/opencode.json"
  export HOME="$B/h" XDG_CONFIG_HOME="$B/xdgconf" XDG_DATA_HOME="$B/xdgdata" \
         XDG_CACHE_HOME="$B/h/.cache" XDG_STATE_HOME="$B/h/.state"
  unset DOCSHELF_CACHE_DIR DOCSHELF_NOTES_DIR
  s=$(date +%s)
  (cd "$B/proj" && timeout "$TIMEOUT" opencode run --standalone --archived --auto \
      --format json --model "$model" "$PROMPT" \
      > "$B/out/zig.jsonl" 2> "$B/out/zig.err")
  e=$?
  echo "zig exit=$e secs=$(( $(date +%s)-s ))" >> "$B/out/summary.txt"
}

for m in "$@"; do
  ( one_model "$m" ) > "$OUT/$(echo "$m" | tr '/:' '__').log" 2>&1 &
done
wait
cat "$OUT"/*/out/summary.txt
echo "score: python3 $HERE/score_trials.py $OUT/*/"
