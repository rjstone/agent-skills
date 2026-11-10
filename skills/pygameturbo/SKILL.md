---
name: pygameturbo
description: Use when someone is writing, debugging or learning a Pygame Turbo (pgturbo, the Pygame Zero fork) game in Python, asks about its hooks (draw, update, on_key_down, ...), built-ins (Actor, screen, images, sounds, music, clock, animate, tone, storage) or running it with pgtrun, or when teaching a beginner game programming with it.
compatibility: Refreshing references/ (scripts/refresh_references.py) needs network access to GitHub; the vendored docs work offline.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Pygame Turbo

Pygame Turbo (`pgturbo`) is a fast-moving fork of Pygame Zero for
education: no event loop, no boilerplate. A game is a script that defines
hook functions (`draw()`, `update()`, `on_key_down()`, ...) and uses
built-in objects (`Actor`, `screen`, `sounds`, `clock`, ...). The API is
small but has sharp edges, and your training data is probably about Pygame
Zero or an older Turbo: **read the matching reference before answering
anything detailed.**

## References

`references/` holds the Pygame Turbo docs sources (`.rst`), verbatim, at the
commit in `references/manifest.json`; each page's online URL is in the
manifest too. License: [`references/README.md`](references/README.md).

| Need | Read |
| --- | --- |
| A map of everything, one section per topic | `references/overview.rst` |
| A beginner course, step by step | `references/tutorials/1_introduction.rst` ... `4_animating_actors.rst` |
| Coming from Scratch | `references/tutorials/from_scratch.rst`, `references/references/scratch.rst` |
| How something works (explanations, examples) | `references/deep_dives/<topic>.rst`: `installation_and_running`, `update_draw_cycle`, `actors`, `screen`, `game_window`, `player_input`, `hooks`, `clock`, `audio`, `resources_and_storage`, `property_animation` |
| Exact API: names, arguments, defaults | `references/references/<topic>.rst`: `actor`, `animate`, `animations`, `clock`, `colors_ref`, `fonts`, `game_window`, `hooks`, `images`, `joystick`, `keyboard`, `mouse`, `music`, `screen`, `sounds`, `storage`, `tone` |
| The bundled example games | `references/examples/overview.rst` (walkthroughs online only) |
| Books, tutorials, videos | `references/misc/resources.rst` |

Not vendored (read online at https://pgturbo.readthedocs.io/): the
example-game walkthroughs, the changelog, other libraries, contributing.
When you point a learner to a page, give its online URL from the manifest.

## Running a game

Outside an IDE, `pgtrun game.py` runs a script. Inside an IDE (Thonny,
IDLE, VS Code, ...) the script must import `pgtrun` first and call
`pgtrun.go()` last, so plain "Run" works
(`references/deep_dives/installation_and_running.rst`):

```python
import pgtrun

WIDTH = 300
HEIGHT = 300

def draw():
    screen.fill((128, 0, 0))

pgtrun.go()
```

`pgtrun` is Turbo's; `pgzrun` is Pygame Zero's. Don't mix them up:
Pygame Zero is older and better represented in training data. Turbo is
otherwise backward-compatible with Pygame Zero and adds features such as
flipbook animation and spritesheets.

## Common pitfalls

- Movement and physics belong in `update()`; `draw()` only paints.
- Hook arguments are passed by position and count:
  `on_mouse_down()`, `on_mouse_down(pos)` and `on_mouse_down(pos, button)`
  all work, but the order is fixed (`deep_dives/hooks.rst`).
- `draw()` takes no arguments; `update()` may take `dt`.
- An Actor's position is its anchor point, which defaults to the center,
  not the top-left corner.
- Images, sounds and music load by name from `images/`, `sounds/` and
  `music/` next to the script, always **without** file extension.
- Key names are attributes of `keyboard` and `keys`; check the exact names
  in `references/references/keyboard.rst`.

## Teaching a beginner

1. Ask what the game should do or what they tried; look at their code and
   any error.
2. When they start a new game, suggest a folder for it (no spaces in the
   name), and let them create it.
3. Start every explanation with which hooks the game needs and what work
   happens in each.
4. Check the exact API detail in `references/` before explaining it.
5. One small step at a time: name the hook or object, show a minimal
   snippet in chat, have them type it, run it and look.
6. Debug by prediction: "what do you expect after this change?", then run.
7. Let the learner install packages themselves (in Thonny: Tools > Manage
   packages); name the package rather than installing it.
8. Keep project facts (the game, its files, assets) in the project's own
   notes, not here: these docs describe the library, not their game.

A good order of first projects: a window with a bouncing ball, one actor
moved by the keyboard, collisions and a score, a scrolling background with
a spawner, sprite animation frames, sound and music, a saved high score
(`references/references/storage.rst`).

## Keeping references current

Never edit `references/`. Refresh from upstream with
`python scripts/refresh_references.py --ref main` (or a tag or commit);
`--check` reports edited or missing files offline, and with `--ref` also
whether upstream moved on. Then review the diff and update the table above
if pages were added, moved or removed.
