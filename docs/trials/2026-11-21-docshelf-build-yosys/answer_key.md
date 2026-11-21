# Answer key

Produced outside the sandbox with the skills under test:

```bash
export DOCSHELF_CACHE_DIR=<empty temp folder>
python3 skills/docshelf-build/scripts/docshelf_build.py build \
  https://yosyshq.readthedocs.io/projects/yosys/en/stable/ --name yosyshq-yosys
python3 <docshelf 0.9.0>/scripts/docshelf.py show yosyshq-yosys:cmd/index_passes_opt#cmd-opt_clean
```

The build kept 49 pages in full and made 65 stubs (1,423 entries, about
3.2 MB on disk, 35 s), and `docshelf list` showed it as `built`.

## Question: options of opt_clean

```
opt_clean [options] [selection]

This pass identifies wires and cells that are unused and removes them. Other
passes often remove cells but leave the wires in the design or reconnect the
wires but leave the old cells in the design. This pass can be used to clean up
after the passes that do the actual work.

This pass only operates on completely selected modules without processes.

-purge
    also remove internal nets if they have a public name
```

So the full answer is: one option, `-purge` (also removes internal nets that
have a public name), plus the optional `[selection]` argument; the pass only
works on completely selected modules without processes.

`-noremove` does not exist in this documentation (a guess in the task
description's grading hint, not a real option). A reply that lists it, or any
other option, made it up.

## Scoring patterns (score_trials.py)

| Check | Pass when the final reply |
|---|---|
| `-purge named` | contains `-purge` |
| `purge meaning` | ties `purge` to internal nets / public name |
| `selection arg` | mentions the selection argument |
| `no invented -noremove` | does not contain `-noremove` |

A reply that was flagged is read by hand before it is called wrong.
