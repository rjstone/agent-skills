#!/usr/bin/env bash
# Run the docshelf trial in opencode, each run in a bubblewrap sandbox.
#
#   run_trials.sh PROVIDER/MODEL [PROVIDER/MODEL ...]
#
# Four runs per model (zig, node, pony, http: questions.md), one after the
# other; models run in parallel. The prompts never name the skill.
#
# Each run sees only: read-only /usr, /etc/ssl, the Node.js runtime folder
# (NODE_DIR, holding opencode), the HTTP docset folder (at /docsets); a
# private /tmp, /proc and /dev; and its model's work folder, writable, as
# /work (also HOME). The work folder holds a copy of the skill
# (~/.claude/skills/docshelf), a docshelf cache with zig, node and pony
# (~/.cache/docshelf), the opencode config and one project folder per run.
# bwrap starts under `env -i`, as an unprivileged host user (setpriv), with
# --clearenv: the run sees no caller environment, no other processes and no
# files outside that view (answer keys and earlier answers stay unreachable).
# Network is shared through the egress proxy; provider keys are placeholders
# that the proxy replaces, so no real key enters the sandbox.
#
# Environment:
#   SRC_CACHE     a docshelf cache holding devdocs/{zig,node,pony} (required)
#   DOCSET_DIR    a folder holding HTTP.docset (required)
#   OUT           output folder, readable by SANDBOX_USER (default: a new
#                 /tmp/docshelf-trial.* folder)
#   TIMEOUT       seconds per run (default 600)
#   NODE_DIR      Node.js folder with bin/opencode (default: from `which opencode`)
#   SANDBOX_USER  host user bwrap runs as (default: sandboxer; created if missing)
#   SMOKE         if set, each run prints what it can see instead of running
#                 a model (env names, /, /root, the repo, docshelf list)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
SKILL="$REPO/skills/docshelf"
[ $# -gt 0 ] || { echo "usage: run_trials.sh PROVIDER/MODEL..." >&2; exit 2; }
command -v bwrap >/dev/null || { echo "bwrap not found (apt-get install -y bubblewrap)" >&2; exit 2; }
SRC_CACHE="$(cd "${SRC_CACHE:?set SRC_CACHE}" && pwd)" || exit 2
DOCSET_DIR="$(cd "${DOCSET_DIR:?set DOCSET_DIR to a folder with HTTP.docset}" && pwd)" || exit 2
[ -d "$DOCSET_DIR/HTTP.docset" ] || { echo "no HTTP.docset in $DOCSET_DIR" >&2; exit 2; }
NODE_DIR="${NODE_DIR:-$(cd "$(dirname "$(command -v opencode)")/.." && pwd)}"
[ -x "$NODE_DIR/bin/opencode" ] || { echo "no bin/opencode in NODE_DIR=$NODE_DIR" >&2; exit 2; }
SANDBOX_USER="${SANDBOX_USER:-sandboxer}"
[ "$SANDBOX_USER" != root ] || { echo "SANDBOX_USER must not be root" >&2; exit 2; }
id -u "$SANDBOX_USER" >/dev/null 2>&1 || useradd -M -s /usr/sbin/nologin "$SANDBOX_USER"
# OUT must be reachable by SANDBOX_USER (a root-only parent such as an
# agent's scratch folder is not): default a fresh folder in /tmp
OUT="${OUT:-$(mktemp -d /tmp/docshelf-trial.XXXXXX)}"
TIMEOUT="${TIMEOUT:-600}"
mkdir -p "$OUT"
chmod 755 "$OUT"
echo "output: $OUT"
# a copy of the docset the sandbox user can read, bound read-only
rm -rf "$OUT/docsets" && mkdir -p "$OUT/docsets"
cp -r "$DOCSET_DIR/HTTP.docset" "$OUT/docsets/" && chmod -R a+rX "$OUT/docsets"
DOCSET_DIR="$OUT/docsets"

# the proxy's CA bundle usually sits under the caller's home, which isn't
# mounted: hand the sandbox a readable copy
CA_COPY="$OUT/ca.crt"
CA_SRC=${SSL_CERT_FILE:-}
[ -r "$CA_SRC" ] || CA_SRC=$HOME/.ccr/ca-bundle.crt
[ -r "$CA_SRC" ] || CA_SRC=/etc/ssl/certs/ca-certificates.crt
cp "$CA_SRC" "$CA_COPY" && chmod 644 "$CA_COPY"

PROXY_ARGS=()
for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy; do
  [ -n "${!v:-}" ] || continue
  case ${!v} in *@*) echo "$v holds credentials; not passing it in" >&2; exit 2 ;; esac
  PROXY_ARGS+=(--setenv "$v" "${!v}")
done

# sandbox WORK MODEL PROMPT RUNDIR: run opencode in bwrap; stdout = events
sandbox() {
  local work="$1" model="$2" prompt="$3" rundir="$4"
  local CMD=(opencode run --standalone --archived --auto --format json
             --model "$model" "$prompt")
  # SMOKE=1: show what a run can see instead of running a model
  [ -n "${SMOKE:-}" ] && CMD=(sh -c 'echo "--- env names:"; env | cut -d= -f1 | sort | tr "\n" " "; echo;
    echo "--- id: $(id -u)"; echo "--- /:"; ls /; echo "--- /root: $(ls /root 2>&1 | head -1)";
    echo "--- repo visible: $(ls '"$REPO"' 2>&1 | head -1)";
    echo "--- docshelf list:"; python3 /work/.claude/skills/docshelf/scripts/docshelf.py list;
    echo "--- opencode: $(opencode --version)"')
  env -i setpriv --reuid "$SANDBOX_USER" --regid "$SANDBOX_USER" --init-groups \
      --inh-caps=-all --bounding-set=-all --no-new-privs \
    /usr/bin/bwrap --unshare-all --share-net --die-with-parent --new-session \
      --uid 1000 --gid 1000 \
      --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib \
      --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin \
      --ro-bind /etc/resolv.conf /etc/resolv.conf --ro-bind /etc/ssl /etc/ssl \
      --ro-bind-try /etc/alternatives /etc/alternatives \
      --ro-bind "$NODE_DIR" "$NODE_DIR" \
      --ro-bind "$DOCSET_DIR" /docsets \
      --ro-bind "$CA_COPY" /ca.crt \
      --proc /proc --dev /dev --tmpfs /tmp --bind "$work" /work --chdir "/work/proj/$rundir" \
      --clearenv --setenv HOME /work --setenv LANG C.UTF-8 \
      --setenv PATH "$NODE_DIR/bin:/usr/local/bin:/usr/bin:/bin" \
      --setenv SSL_CERT_FILE /ca.crt --setenv CURL_CA_BUNDLE /ca.crt \
      --setenv REQUESTS_CA_BUNDLE /ca.crt --setenv NODE_EXTRA_CA_CERTS /ca.crt \
      "${PROXY_ARGS[@]}" \
      --setenv DOCSHELF_DOCSET_DIRS /docsets \
      --setenv OPENCODE_API_KEY proxy-injected --setenv OPENROUTER_API_KEY proxy-injected \
      --setenv NOUS_API_KEY proxy-injected --setenv REFLECTION_API_KEY proxy-injected \
      -- "${CMD[@]}"
}

TAIL="Quote the documentation and give the reference you found each answer in."
P_ZIG="Using the offline Zig 0.17.1 documentation available on this machine, answer these questions. $TAIL
(1) What do @divFloor(-5, 3) and @divTrunc(-5, 3) evaluate to?
(2) How do you make a continue statement jump to another prong of a switch in Zig, and what must such a continue include?
(3) In Zig 0.17.1, how do you construct the integer type u18 at comptime from a signedness and a bit width? Give the builtin's exact signature."
P_NODE="Using the offline Node.js 26.3.1 documentation available on this machine, answer these questions. $TAIL
(1) What does path.basename('/foo/bar/baz/asdf/quux.html', '.html') return?
(2) In Node.js's built-in node:sqlite, what are the default values of the enableForeignKeyConstraints and defensive options of new DatabaseSync(path, options), and in which Node.js versions did defensive become enabled by default?
(3) A Node.js 26 process was started with --permission --allow-fs-read=*. Can it call process.permission.drop('fs.read', '/etc/myapp') to revoke read access to just that directory? If not, what can it do instead? In which Node.js version was process.permission.drop() added?"
P_PONY="Using the offline Pony 0.38.1 standard library documentation available on this machine, answer these questions. $TAIL
(1) In a Pony Main actor, how do you print a line to standard output, and what is the declared type (with reference capability) of the field you use?
(2) In Pony 0.38.1's standard library, what is the declared type of Env.root, and why does it have that type?
(3) Three Promise[String val] values p1, p2, p3 are joined with Promises[String val].join([p1; p2; p3].values()), then fulfilled in the order p2, p3, p1. In what order do the values appear in the joined array? Also give the full signature of Promise.next, including reference capabilities of its parameters and return type."
P_HTTP="Using the offline HTTP reference (MDN) available on this machine, answer these questions. $TAIL
(1) Which HTTP status code means \"Too Many Requests\", and which response header may tell the client how long to wait before trying again?
(2) In the Priority request header, what values can the urgency parameter take, which end is the highest priority, what is its default for requests, is there a default for responses, and what does the i parameter mean?
(3) What No-Vary-Search header value makes the browser ignore every URL query parameter for cache matching except id and lang? What does the key-order directive do?"

one_model() {
  local model="$1" slug B W s e set prompt
  slug=$(echo "$model" | tr '/:' '__')
  B="$OUT/$slug"
  W="$B/work"
  rm -rf "$B"
  mkdir -p "$W/.claude/skills" "$W/.cache/docshelf/devdocs" "$W/.config/opencode" "$B/out"
  cp -r "$SKILL" "$W/.claude/skills/docshelf"
  find "$W/.claude/skills/docshelf" -name __pycache__ -prune -exec rm -rf {} +
  for d in zig node pony; do cp -r "$SRC_CACHE/devdocs/$d" "$W/.cache/docshelf/devdocs/"; done
  [ -f "$SRC_CACHE/devdocs/docs.json" ] && cp "$SRC_CACHE/devdocs/docs.json" "$W/.cache/docshelf/devdocs/"
  cp "$HERE/opencode.json" "$W/.config/opencode/opencode.json"
  for set in zig node pony http; do mkdir -p "$W/proj/$set"; done
  chown -R "$SANDBOX_USER:" "$W"
  for set in zig node pony http; do
    case $set in zig) prompt=$P_ZIG ;; node) prompt=$P_NODE ;;
                 pony) prompt=$P_PONY ;; http) prompt=$P_HTTP ;; esac
    s=$(date +%s)
    timeout "$TIMEOUT" bash -c "$(declare -f sandbox); $(declare -p NODE_DIR DOCSET_DIR CA_COPY SANDBOX_USER PROXY_ARGS REPO); SMOKE=${SMOKE:-}; sandbox \"\$@\"" _ \
      "$W" "$model" "$prompt" "$set" > "$B/out/$set.jsonl" 2> "$B/out/$set.err"
    e=$?
    echo "$set exit=$e secs=$(( $(date +%s)-s ))" >> "$B/out/summary.txt"
  done
}

for m in "$@"; do
  ( one_model "$m" ) > "$OUT/$(echo "$m" | tr '/:' '__').log" 2>&1 &
done
wait
cat "$OUT"/*/out/summary.txt
echo "score: python3 $HERE/score_trials.py $OUT/*/"
