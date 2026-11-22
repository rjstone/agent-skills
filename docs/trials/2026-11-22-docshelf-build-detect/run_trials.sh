#!/usr/bin/env bash
# Run the docshelf-build 0.2.0 routing trial: two sites (a Sphinx site and an
# llms.txt site), skill arm only, in opencode, each run in a bubblewrap
# sandbox (the sandboxing skill's scripts/sandbox.py). Adapted from
# ../2026-11-21-docshelf-build-yosys/run_trials.sh, which also ran a no-skill
# baseline.
#
#   run_trials.sh PROVIDER/MODEL [PROVIDER/MODEL ...]
#
# docshelf-build and docshelf are copied to /work/.claude/skills. Per model
# the sites run one after the other; models run in parallel. The prompts
# never name a skill. A run with no model reply (e.g. HTTP 429) is retried
# once.
#
# Environment:
#   SITES         which prompts to run (default "sphinx llms")
#   OUT           output folder, readable by SANDBOX_USER (default: new /tmp/...)
#   TIMEOUT       seconds per run (default 1200)
#   NODE_DIR      Node.js folder holding bin/opencode (default: from PATH)
#   SANDBOX_USER  host user bwrap runs as (default sandboxer)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
BUILD_SKILL="$REPO/skills/docshelf-build"
DOCSHELF_SKILL="$REPO/skills/docshelf"
SANDBOX="$REPO/skills/sandboxing/scripts/sandbox.py"
[ $# -gt 0 ] || { echo "usage: run_trials.sh PROVIDER/MODEL..." >&2; exit 2; }
command -v bwrap >/dev/null || { echo "bwrap not found (apt-get install -y bubblewrap)" >&2; exit 2; }
NODE_DIR="${NODE_DIR:-$(cd "$(dirname "$(command -v opencode)")/.." && pwd)}"
SANDBOX_USER="${SANDBOX_USER:-sandboxer}"
id -u "$SANDBOX_USER" >/dev/null 2>&1 || useradd -M -s /usr/sbin/nologin "$SANDBOX_USER"
OUT="${OUT:-$(mktemp -d /tmp/docshelf-build-trial.XXXXXX)}"
TIMEOUT="${TIMEOUT:-1200}"
SITES="${SITES:-sphinx llms}"
mkdir -p "$OUT"; chmod 755 "$OUT"
echo "output: $OUT"

prompt() {
  case "$1" in
    sphinx) echo "I want the Yosys documentation (https://yosyshq.readthedocs.io/projects/yosys/en/stable/) available offline on this machine so I can look things up later without the web. Set that up, then using only the offline copy tell me what options the opt_clean pass accepts and what each does." ;;
    llms) echo "I want the LangChain documentation (https://docs.langchain.com/) available offline on this machine so I can look things up later without the web. I only use the Python SDK. Set that up, then using only the offline copy tell me what values create_agent's response_format parameter accepts, and what happens when I pass a schema type directly." ;;
  esac
}

run_once() {  # WORK MODEL OUTFILE PROMPT
  python3 "$SANDBOX" --user "$SANDBOX_USER" --work "$1" --ro "$NODE_DIR" \
    --setenv OPENCODE_API_KEY=proxy-injected --setenv OPENROUTER_API_KEY=proxy-injected \
    --setenv NOUS_API_KEY=proxy-injected \
    -- sh -c 'cd /work/proj && exec "$@"' _ \
    opencode run --standalone --archived --auto --format json --model "$2" "$4" \
    > "$3" 2> "${3%.jsonl}.err"
}

one_site() {  # MODEL SITE
  local model="$1" site="$2" slug W s e tries=0 p
  p=$(prompt "$site")
  slug=$(echo "$model" | tr '/:' '__')-$site
  W="$OUT/$slug/work"
  rm -rf "$OUT/$slug"
  mkdir -p "$W/.claude/skills" "$W/.config/opencode" "$W/proj" "$OUT/$slug/out"
  cp "$HERE/opencode.json" "$W/.config/opencode/opencode.json"
  cp -r "$BUILD_SKILL" "$W/.claude/skills/docshelf-build"
  cp -r "$DOCSHELF_SKILL" "$W/.claude/skills/docshelf"
  find "$W" -name __pycache__ -prune -exec rm -rf {} +
  chown -R "$SANDBOX_USER:" "$W"
  while :; do
    s=$(date +%s)
    timeout "$TIMEOUT" bash -c "$(declare -f run_once); $(declare -p NODE_DIR SANDBOX_USER SANDBOX); run_once \"\$@\"" _ \
      "$W" "$model" "$OUT/$slug/out/run.jsonl" "$p"
    e=$?
    echo "exit=$e secs=$(( $(date +%s)-s )) try=$((tries+1))" > "$OUT/$slug/out/summary.txt"
    tries=$((tries+1))
    if [ $tries -lt 2 ] && ! grep -q '"type":"text"' "$OUT/$slug/out/run.jsonl" 2>/dev/null; then
      cp "$OUT/$slug/out/run.jsonl" "$OUT/$slug/out/failed-try1.jsonl" 2>/dev/null
      rm -rf "$W/proj"/* "$W/.cache" "$W/.local" "$W/.opencode" 2>/dev/null
      continue
    fi
    break
  done
  ( cd "$W" && du -sb .[!.]* * 2>/dev/null ) > "$OUT/$slug/out/disk.txt"
}

for m in "$@"; do
  ( for site in $SITES; do one_site "$m" "$site"; done ) > "$OUT/$(echo "$m" | tr '/:' '__').log" 2>&1 &
done
wait
for f in "$OUT"/*/out/summary.txt; do echo "$f: $(cat "$f")"; done
echo "score: python3 $HERE/score_trials.py $OUT/*/"
