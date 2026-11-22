# Answer key

## sphinx: Yosys `opt_clean`

From the 2026-11-21 trial's key (`docshelf show` on the built docvol): one
option, `-purge` (also remove internal nets that have a public name), plus
the `[selection]` argument. No other option exists; `-noremove` is made up.

## llms: LangChain `create_agent(response_format=...)`

From `docshelf show <docvol>:oss/python/langchain/structured-output` on a
docvol built from the `build/python.txt` sub-index (2026-11-21):

- `response_format` accepts `ToolStrategy[T]` (structured output through
  tool calling), `ProviderStrategy[T]` (provider-native structured output),
  a schema type `type[T]` (the strategy is chosen automatically), or `None`
  (no structured output).
- A schema type passed directly: LangChain uses `ProviderStrategy` when the
  model and provider support native structured output (read from the model's
  profile data with langchain>=1.1), else `ToolStrategy`.
- JSON Schema dictionaries are not detected automatically: they must be
  wrapped in an explicit `ProviderStrategy` or `ToolStrategy`.
- The result is in the `structured_response` key of the agent's final state.
