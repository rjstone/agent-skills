# GUI plugins: local additions

Supplements `plugins-gui.md`. Not from the opencode docs site: written for
this skill from the installed `@opencode/plugin@2.2.5` GUI type declarations
(`dist/gui/*.d.ts`) and the opencode source at `v2.2.5` and `v2.2.6`.
Re-check after an opencode upgrade; the installed types win on any conflict.

Code (https://github.com/anomalyco/opencode): the GUI plugin API is
`packages/plugin/src/gui/`; the Desktop app is `packages/desktop/` (Electron:
`src/main`, `src/preload`, `src/renderer`), its UI `packages/app/`, built-in
GUI plugins `packages/gui-plugins/`.

## Registries

### Styles

#### Notes

- No API hides or disables the app's own controls (model, effort, agent
  pickers, ...). `Style` (CSS while the contribution is active) is the only
  route, and depends on the app's internal class names: may break on an
  opencode update.

## Host APIs

### Sessions and the session screen

#### Notes

- No API adds a timeline entry the model does not see. Synthetic messages
  (`session.synthetic`) are part of `session.context`, the model-visible
  history (see `client.local.md`). For user-only output use a panel tab
  (`ctx.layout.open`), `ctx.toast`, a dialog, a composer pill or a slot.

### Choose the model

#### Notes

- No `setAgent`: `Composer` has `setModel` / `setVariant` but nothing that
  selects the agent (2.2.5 types, 2.2.6 source). A GUI part cannot switch
  the session's agent the way the picker does.
- The Desktop picker shows the session's local selection before the
  server's: `scope()?.agent ?? durable()?.agent`
  (`packages/app/src/providers/models/selection.tsx`). Any pick in that
  session (agent, model or variant) creates the local selection; it is
  persisted, so it survives restarts.
  - Only the app's own commits release it, when the server echoes exactly
    what the app sent. A switch made elsewhere (`ctx.session.switchAgent`
    in a server plugin, the TUI, another client) never matches, so the
    picker keeps the old agent.
  - Each steer submission from Desktop re-applies the composer's selection
    (`if (current?.agent !== selection.agent) switchAgent(...)`,
    `packages/app/src/composer/submit.ts`): the next message switches the
    session back.
  - 2.2.6 rewrote this as `selection-machine.ts` with the same rule
    (phases `override` / `awaiting-ack` / `committed`); an ack timeout
    (10 s) falls back to the local selection.
  - A session nobody picked in follows the server's agent.
- Calling the server's `switchAgent` from a GUI part hits the same rule.
