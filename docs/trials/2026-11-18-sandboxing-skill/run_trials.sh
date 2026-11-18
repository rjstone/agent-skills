#!/usr/bin/env bash
# Run the Zig docshelf trial in opencode, each run sandboxed by the
# sandboxing skill's sandbox.py (instead of a hand-written bwrap command).
#
#   run_trials.sh PROVIDER/MODEL [PROVIDER/MODEL ...]
#
# One run per model (the Zig questions of
# ../2026-11-18-opencode-docshelf-sandboxed/questions.md); models run in
# parallel. The prompt never names the skill.
#
# Each run sees only what sandbox.py gives it: read-only /usr and /etc/ssl,
# the Node.js runtime folder (NODE_DIR, holding opencode; its bin/ goes on
# PATH), a private /tmp, /proc and /dev, and its model's work folder,
# writable, as /work (also HOME). The work folder holds a copy of the
# docshelf skill (~/.claude/skills/docshelf), a docshelf cache with zig
# (~/.cache/docshelf) and the opencode config. Provider keys are
# placeholders that the egress proxy replaces.
#
# Environment:
#   SRC_CACHE  a docshelf cache holding devdocs/zig (required)
#   OUT        output folder (default: a new /tmp/sandboxing-trial.* folder)
#   TIMEOUT    seconds per run (default 600)
#   NODE_DIR   Node.js folder with bin/opencode (default: from `which opencode`)
#   SMOKE      if set, each run prints what it can see instead of running a model
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
SKILL="$REPO/skills/docshelf"
SANDBOX="$REPO/skills/sandboxing/scripts/sandbox.py"
PREV="$REPO/docs/trials/2026-11-18-opencode-docshelf-sandboxed"
[ $# -gt 0 ] || { echo "usage: run_trials.sh PROVIDER/MODEL..." >&2; exit 2; }
SRC_CACHE="$(cd "${SRC_CACHE:?set SRC_CACHE}" && pwd)" || exit 2
[ -d "$SRC_CACHE/devdocs/zig" ] || { echo "no devdocs/zig in $SRC_CACHE" >&2; exit 2; }
NODE_DIR="${NODE_DIR:-$(cd "$(dirname "$(command -v opencode)")/.." && pwd)}"
[ -x "$NODE_DIR/bin/opencode" ] || { echo "no bin/opencode in NODE_DIR=$NODE_DIR" >&2; exit 2; }
OUT="${OUT:-$(mktemp -d /tmp/sandboxing-trial.XXXXXX)}"
TIMEOUT="${TIMEOUT:-600}"
mkdir -p "$OUT"
chmod 755 "$OUT"   # sandbox.py refuses a --work folder the sandbox user cannot reach
echo "output: $OUT"

P_ZIG="Using the offline Zig 0.17.1 documentation available on this machine, answer these questions. Quote the documentation and give the reference you found each answer in.
(1) What do @divFloor(-5, 3) and @divTrunc(-5, 3) evaluate to?
(2) How do you make a continue statement jump to another prong of a switch in Zig, and what must such a continue include?
(3) In Zig 0.17.1, how do you construct the integer type u18 at comptime from a signedness and a bit width? Give the builtin's exact signature."

one_model() {
  local model="$1" slug B W s e
  slug=$(echo "$model" | tr '/:' '__')
  B="$OUT/$slug"
  W="$B/work"
  rm -rf "$B"
  mkdir -p "$W/.claude/skills" "$W/.cache/docshelf/devdocs" "$W/.config/opencode" "$W/proj/zig" "$B/out"
  cp -r "$SKILL" "$W/.claude/skills/docshelf"
  find "$W/.claude/skills/docshelf" -name __pycache__ -prune -exec rm -rf {} +
  cp -r "$SRC_CACHE/devdocs/zig" "$W/.cache/docshelf/devdocs/"
  [ -f "$SRC_CACHE/devdocs/docs.json" ] && cp "$SRC_CACHE/devdocs/docs.json" "$W/.cache/docshelf/devdocs/"
  cp "$PREV/opencode.json" "$W/.config/opencode/opencode.json"
  local CMD=(opencode run --standalone --archived --auto --format json --model "$model" "$P_ZIG")
  [ -n "${SMOKE:-}" ] && CMD=(sh -c 'echo "--- env names:"; env | cut -d= -f1 | sort | tr "\n" " "; echo;
    echo "--- id: $(id -u)"; echo "--- /:"; ls /; echo "--- /root: $(ls /root 2>&1 | head -1)";
    echo "--- docshelf list:"; python3 /work/.claude/skills/docshelf/scripts/docshelf.py list;
    echo "--- opencode: $(opencode --version)"')
  s=$(date +%s)
  timeout "$TIMEOUT" python3 "$SANDBOX" --work "$W" --ro "$NODE_DIR" \
      --setenv OPENCODE_API_KEY=proxy-injected --setenv OPENROUTER_API_KEY=proxy-injected \
      --setenv NOUS_API_KEY=proxy-injected --setenv REFLECTION_API_KEY=proxy-injected \
      -- sh -c 'cd /work/proj/zig && exec "$@"' sh "${CMD[@]}" \
      > "$B/out/zig.jsonl" 2> "$B/out/zig.err"
  e=$?
  echo "zig exit=$e secs=$(( $(date +%s)-s ))" >> "$B/out/summary.txt"
}

for m in "$@"; do
  ( one_model "$m" ) > "$OUT/$(echo "$m" | tr '/:' '__').log" 2>&1 &
done
wait
cat "$OUT"/*/out/summary.txt
echo "score: python3 $PREV/score_trials.py $OUT/*/"
