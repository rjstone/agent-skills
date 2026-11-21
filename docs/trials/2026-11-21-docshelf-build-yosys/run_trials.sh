#!/usr/bin/env bash
# Run the docshelf-build trial: one prompt, two arms, in opencode, each run in
# a bubblewrap sandbox (the sandboxing skill's scripts/sandbox.py).
#
#   run_trials.sh PROVIDER/MODEL [PROVIDER/MODEL ...]
#
# Arm "skill": docshelf-build and docshelf copied to /work/.claude/skills.
# Arm "base":  no skills. Per model the arms run one after the other; models
# run in parallel. The prompt never names a skill. A run that ends with a
# provider error and no reply (e.g. HTTP 429) is retried once.
#
# Environment:
#   DOCSHELF_SKILL  docshelf skill folder (default: ../../../skills/docshelf;
#                   must be a version that lists built docvols, 0.9.0+)
#   OUT             output folder, readable by SANDBOX_USER (default: new /tmp/...)
#   TIMEOUT         seconds per run (default 900)
#   NODE_DIR        Node.js folder holding bin/opencode (default: from PATH)
#   SANDBOX_USER    host user bwrap runs as (default sandboxer)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
BUILD_SKILL="$REPO/skills/docshelf-build"
DOCSHELF_SKILL="${DOCSHELF_SKILL:-$REPO/skills/docshelf}"
SANDBOX="$REPO/skills/sandboxing/scripts/sandbox.py"
[ $# -gt 0 ] || { echo "usage: run_trials.sh PROVIDER/MODEL..." >&2; exit 2; }
command -v bwrap >/dev/null || { echo "bwrap not found (apt-get install -y bubblewrap)" >&2; exit 2; }
NODE_DIR="${NODE_DIR:-$(cd "$(dirname "$(command -v opencode)")/.." && pwd)}"
SANDBOX_USER="${SANDBOX_USER:-sandboxer}"
id -u "$SANDBOX_USER" >/dev/null 2>&1 || useradd -M -s /usr/sbin/nologin "$SANDBOX_USER"
OUT="${OUT:-$(mktemp -d /tmp/docshelf-build-trial.XXXXXX)}"
TIMEOUT="${TIMEOUT:-900}"
mkdir -p "$OUT"; chmod 755 "$OUT"
echo "output: $OUT"

PROMPT="I want the Yosys documentation (https://yosyshq.readthedocs.io/projects/yosys/en/stable/) available offline on this machine so I can look things up later without the web. Set that up, then using only the offline copy tell me what options the opt_clean pass accepts and what each does."

run_once() {  # WORK MODEL OUTFILE
  python3 "$SANDBOX" --user "$SANDBOX_USER" --work "$1" --ro "$NODE_DIR" \
    --setenv OPENCODE_API_KEY=proxy-injected --setenv OPENROUTER_API_KEY=proxy-injected \
    --setenv NOUS_API_KEY=proxy-injected \
    -- sh -c 'cd /work/proj && exec "$@"' _ \
    opencode run --standalone --archived --auto --format json --model "$2" "$PROMPT" \
    > "$3" 2> "${3%.jsonl}.err"
}

one_arm() {  # MODEL ARM
  local model="$1" arm="$2" slug W s e tries=0
  slug=$(echo "$model" | tr '/:' '__')-$arm
  W="$OUT/$slug/work"
  rm -rf "$OUT/$slug"
  mkdir -p "$W/.claude/skills" "$W/.config/opencode" "$W/proj" "$OUT/$slug/out"
  cp "$HERE/opencode.json" "$W/.config/opencode/opencode.json"
  if [ "$arm" = skill ]; then
    cp -r "$BUILD_SKILL" "$W/.claude/skills/docshelf-build"
    cp -r "$DOCSHELF_SKILL" "$W/.claude/skills/docshelf"
    find "$W" -name __pycache__ -prune -exec rm -rf {} +
  fi
  chown -R "$SANDBOX_USER:" "$W"
  while :; do
    s=$(date +%s)
    timeout "$TIMEOUT" bash -c "$(declare -f run_once); $(declare -p NODE_DIR SANDBOX_USER SANDBOX PROMPT); run_once \"\$@\"" _ \
      "$W" "$model" "$OUT/$slug/out/run.jsonl"
    e=$?
    echo "exit=$e secs=$(( $(date +%s)-s )) try=$((tries+1))" > "$OUT/$slug/out/summary.txt"
    tries=$((tries+1))
    # retry once when no model reply came back
    if [ $tries -lt 2 ] && ! grep -q '"type":"text"' "$OUT/$slug/out/run.jsonl" 2>/dev/null; then
      cp "$OUT/$slug/out/run.jsonl" "$OUT/$slug/out/failed-try1.jsonl" 2>/dev/null
      rm -rf "$W/proj"/* "$W/.cache" "$W/.local" "$W/.opencode" 2>/dev/null
      continue
    fi
    break
  done
  # what the run left on disk, by top-level folder of /work (bytes)
  ( cd "$W" && du -sb .[!.]* * 2>/dev/null ) > "$OUT/$slug/out/disk.txt"
}

for m in "$@"; do
  ( one_arm "$m" skill; one_arm "$m" base ) > "$OUT/$(echo "$m" | tr '/:' '__').log" 2>&1 &
done
wait
for f in "$OUT"/*/out/summary.txt; do echo "$f: $(cat "$f")"; done
echo "score: python3 $HERE/score_trials.py $OUT/*/"
