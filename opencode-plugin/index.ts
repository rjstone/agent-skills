// opencode v2 server plugin: adds the agent-skills skills of the chosen sets.
//
//   "plugins": [{ "package": "<this repo or package>", "options": { "sets": ["docshelf"] } }]
//
// Sets come from opencode-plugin/sets.json (generated from skill-sets.json by
// scripts/build_plugins.py). Skills are read in place from skills/<name>/.
// Imports only @opencode/plugin (provided by opencode) and Node built-ins.
import { Plugin, Skill } from "@opencode/plugin"
import { readFile } from "node:fs/promises"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { loadSkills, planAdds, resolveSets } from "./skills.ts"

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))

export default Plugin.define({
  id: "agent-skills",
  async setup(ctx) {
    const sets = JSON.parse(await readFile(join(ROOT, "opencode-plugin", "sets.json"), "utf8"))
    const names = resolveSets(ctx.options.sets, sets)
    if (names.length === 0) {
      console.warn(`agent-skills: no "sets" option, so no skills added; known sets: ${Object.keys(sets).join(", ")}`)
      return
    }
    const entries = await loadSkills(ROOT, names)
    await ctx.skill.transform((editor) => {
      const existing = new Set<string>(editor.list().map((s: { id: string }) => s.id))
      const { add, skipped } = planAdds(existing, entries)
      for (const id of skipped) console.warn(`agent-skills: skill "${id}" is already loaded; left as is`)
      for (const e of add) {
        editor.add({
          id: Skill.ID.make(e.id),
          name: Skill.Name.make(e.name),
          description: e.description,
          path: Skill.Info.fields.path.make(e.path),
          content: e.content,
        })
      }
    })
  },
})
