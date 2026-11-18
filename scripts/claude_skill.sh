#!/usr/bin/env bash
# Package skills as Claude .skill files (zip archives with the skill folder at
# the top level, which is what Claude's skill upload expects).
#
#   scripts/claude_skill.sh [-o OUTDIR] [-l] [SKILL...]
#
# With no SKILL arguments every skill under ../skills (relative to this
# script, not the current directory) is packaged; otherwise only the named
# ones. Writes <name>.skill into OUTDIR (default: the current directory).
# -l lists the available skills and exits.
#
# Each skill is checked first: SKILL.md must exist, start with a frontmatter
# block, and carry a `name` equal to the folder name and a `description`.
# Left out of the archive: evals/ at the skill root, __pycache__, node_modules,
# *.pyc and .DS_Store. Needs `zip`. Exit status is 1 if any skill failed.

set -u

base="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skills_dir="$base/../skills"
outdir="."
list_only=0

usage() { sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while getopts "o:lh" opt; do
  case "$opt" in
    o) outdir="$OPTARG" ;;
    l) list_only=1 ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

if [ ! -d "$skills_dir" ]; then
  echo "error: skills directory not found: $skills_dir" >&2
  exit 2
fi
skills_dir="$(cd "$skills_dir" && pwd)"

available=()
for d in "$skills_dir"/*/; do
  [ -f "${d}SKILL.md" ] && available+=("$(basename "$d")")
done

if [ "$list_only" = 1 ]; then
  printf '%s\n' "${available[@]}"
  exit 0
fi

if [ "$#" -gt 0 ]; then
  names=("$@")
else
  names=("${available[@]}")
fi

command -v zip >/dev/null 2>&1 || { echo "error: zip is not installed" >&2; exit 2; }
mkdir -p "$outdir" || exit 2
outdir="$(cd "$outdir" && pwd)"

# Print the value of a top-level frontmatter key, or nothing.
fm_value() {
  awk -v key="$2" '
    NR == 1 { if ($0 != "---") exit; next }
    $0 == "---" { exit }
    index($0, key ":") == 1 { sub("^" key ":[ \t]*", ""); print; exit }
  ' "$1"
}

failed=0
for name in "${names[@]}"; do
  dir="$skills_dir/$name"
  if [ ! -f "$dir/SKILL.md" ]; then
    echo "FAIL $name: no skills/$name/SKILL.md" >&2; failed=1; continue
  fi
  if [ "$(head -n 1 "$dir/SKILL.md")" != "---" ]; then
    echo "FAIL $name: SKILL.md has no frontmatter" >&2; failed=1; continue
  fi
  fm_name="$(fm_value "$dir/SKILL.md" name)"
  fm_desc="$(fm_value "$dir/SKILL.md" description)"
  if [ "$fm_name" != "$name" ]; then
    echo "FAIL $name: frontmatter name '$fm_name' != folder name" >&2; failed=1; continue
  fi
  if [ -z "$fm_desc" ]; then
    echo "FAIL $name: frontmatter has no description" >&2; failed=1; continue
  fi

  out="$outdir/$name.skill"
  rm -f "$out"
  if (cd "$skills_dir" && zip -qr "$out" "$name" \
        -x "$name/evals/*" '*/__pycache__/*' '*/node_modules/*' '*.pyc' '*.DS_Store'); then
    echo "ok   $name -> $out"
  else
    echo "FAIL $name: zip failed" >&2; failed=1
  fi
done

exit "$failed"
