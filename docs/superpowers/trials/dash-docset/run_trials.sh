#!/usr/bin/env bash
# Run the dash-docset agent trials in opencode, one isolated home per model.
#
#   run_trials.sh SET PROVIDER/MODEL [PROVIDER/MODEL ...]
#
# SET is "basic" (four short scenarios: two lookups with a store already
# set up, then asking for Flask, which isn't there, in a project and on a
# machine with nothing set up) or "docsets" (four full tasks: set up a
# store that reads $DOCSETS, three lookups, one note).
# Models run in parallel; a model's runs are sequential.
#
# The script downloads no docsets (it never contacts kapeli.com), so the
# docsets come from a folder you supply, e.g. a copy of Zeal's docset
# folder. It must hold: basic: Pandas, Jinja (not Flask); docsets: DuckDB,
# Solarus, Python 3, the Git cheat sheet, Arm Morello A64 ISA.
#
# Environment:
#   DOCSETS  that folder (required); runs only read it
#   OUT      output folder (default: a new temporary folder, printed at start)
#   TIMEOUT  seconds per run (default 600)
#   The provider key variables opencode reads (OPENCODE_API_KEY,
#   OPENROUTER_API_KEY, NOUS_API_KEY, REFLECTION_API_KEY, ...). Any that is
#   unset is set to a placeholder, which is right when an egress proxy
#   injects the real key and wrong otherwise.
#
# Score the result with score_trials.py. Background and results:
# ../../plans/2026-11-14-dash-docset-after-plan.md
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../../.." && pwd)
SKILL="$REPO/skills/dash-docset"
DOCSET="python3 $SKILL/scripts/docset.py"
SET="${1:?usage: run_trials.sh basic|docsets PROVIDER/MODEL...}"
shift
[ $# -gt 0 ] || { echo "name at least one provider/model" >&2; exit 2; }
DOCSETS="$(cd "${DOCSETS:?set DOCSETS to a folder of .docset folders}" && pwd)" || exit 2
OUT="${OUT:-$(mktemp -d)}"
TIMEOUT="${TIMEOUT:-600}"
mkdir -p "$OUT"
echo "output: $OUT"
for v in OPENCODE_API_KEY OPENROUTER_API_KEY NOUS_API_KEY REFLECTION_API_KEY; do
  [ -n "${!v:-}" ] || export "$v=proxy-injected"
done

PRE="Set up offline Dash docsets for this project. Use the folder .docsets inside this project folder as the docset store (I approve that location; this is a throwaway sandbox). The docsets I downloaded with Zeal are in $DOCSETS."
POST="Answer each question with a short quote from the docset and the reference you found it in."

one_model() {
  local model="$1" slug B
  slug=$(echo "$model" | tr '/:' '__')
  B="$OUT/$SET/$slug"
  rm -rf "$B"
  # $B/h is the agent's home folder
  mkdir -p "$B/h/.claude/skills" "$B/xdgconf/opencode" "$B/xdgdata" "$B/out"
  # the only skill the agent sees; the link stays outside the repo
  ln -s "$SKILL" "$B/h/.claude/skills/dash-docset"
  cp "$HERE/opencode.json" "$B/xdgconf/opencode/opencode.json"
  export HOME="$B/h" XDG_CONFIG_HOME="$B/xdgconf" XDG_DATA_HOME="$B/xdgdata" \
         XDG_CACHE_HOME="$B/h/.cache" XDG_STATE_HOME="$B/h/.state"

  run() { # id folder prompt
    local id="$1" dir="$2" prompt="$3" s e
    mkdir -p "$dir"
    s=$(date +%s)
    (cd "$dir" && timeout "$TIMEOUT" opencode run --standalone --archived --auto \
        --format json --model "$model" "$prompt" \
        > "$B/out/$id.jsonl" 2> "$B/out/$id.err")
    e=$?
    echo "$id exit=$e secs=$(( $(date +%s)-s ))" >> "$B/out/summary.txt"
    # what the run left behind: store, docsets, notes
    (cd "$dir" && { $DOCSET where; $DOCSET list
      for n in $($DOCSET list 2>/dev/null | awk '{print $1}'); do
        echo "--- notes $n"; $DOCSET notes "$n" --check
        f=$($DOCSET notes "$n" --path 2>/dev/null); [ -f "$f" ] && cat "$f"
      done; echo "--- files"; ls -a; } > "$B/out/$id.state.txt" 2>&1)
  }

  if [ "$SET" = basic ]; then
    mkdir -p "$B/proj"
    (cd "$B/proj" && $DOCSET where --set store --project --read-from "$DOCSETS" >/dev/null)
    run S1 "$B/proj" "Using the offline docsets installed for this project, what is the default value of the on_bad_lines parameter of pandas.read_csv, and what values does it accept? Quote the documentation."
    run S2 "$B/proj" "Check the offline Jinja docset: what is the exact signature of the batch filter, and what does its last argument do? Quote the docset."
    # Flask is not in $DOCSETS: the right answer sends the user to Dash or Zeal
    run S3 "$B/proj" "I need Flask reference offline. Add the Flask docset to this project's docset store, then tell me the exact signature of flask.redirect and its default status code, quoted from the docset."
    run S4 "$B/cold" "Set up Dash docsets on this machine so I can look up Flask docs offline."
  else
    run duckdb "$B/duckdb" "$PRE Use the DuckDB docset. Then: (1) For the dates 1992-09-15 and 1992-11-14, what do date_diff and date_sub return in months, and why do they differ? (2) What are the type and default of read_csv's skip parameter? (3) What does count_if(42) return? Finally add a note to the docset for count_if that says 'A non-zero number counts as true.' and check that the note is attached. $POST"
    run solarus "$B/solarus" "$PRE Use the Solarus docset (a Lua game engine API). Then: (1) How do I make a timer repeat, and when is a timer whose context is an enemy cancelled automatically? (2) What exact call makes an enemy unaffected by arrows? (3) What is the hero's default walking speed? Finally add a note to the docset for sol.timer.start that says 'Return true from the callback to repeat.' and check that the note is attached. $POST"
    run python "$B/python" "$PRE Use the Python 3 docset and the Git cheat sheet. Then: (1) What is the default of asyncio.gather's return_exceptions, and what happens to exceptions when it is True? (2) From the Git cheat sheet: which form of git reset preserves uncommitted local changes? (3) Use full-text search to find which class has a get() method that returns 'a value for the context variable for the current context'. Finally add a note to the Python docset for asyncio.gather that says 'return_exceptions=True puts exceptions in the result list.' and check that the note is attached. $POST"
    run morello "$B/morello" "$PRE Use the Arm Morello A64 instruction set docset. Then: (1) What is the difference between SCBNDS (register) and SCBNDSE when the bounds cannot be set exactly? (2) What is the assembler syntax of GCBASE, and what does register number 31 select for its source operand? (3) Which bit positions hold the Cn and Rd fields in GCBASE's encoding? Finally add a note to the docset for GCBASE that says 'Cn=31 selects CSP.' and check that the note is attached. $POST"
  fi
  echo done >> "$B/out/summary.txt"
}

for m in "$@"; do
  ( one_model "$m" ) > "$OUT/$SET-$(echo "$m" | tr '/:' '__').log" 2>&1 &
done
wait
cat "$OUT/$SET"/*/out/summary.txt
echo "score: python3 $HERE/score_trials.py $OUT/$SET/*/"
