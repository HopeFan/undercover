# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.

## Design

7. One module per external service. Its address is defined once, and nothing else builds its URLs or sends it requests.
8. Modules use each other only through their public functions. No module reaches into another's internals, and imports never go in a circle.
9. An agent's tools all live in one module. Run state reaches a tool through the framework's context (in LangChain, `context_schema` with `ToolRuntime`), never through closures or shared variables.
10. Use the framework's own features, such as its middleware, context and error handling, before writing your own.
11. Don't repeat logic. A pattern written twice becomes one function.
12. Agent instructions give the agent a goal, what it has to work with and its limits. Keep the business rules; leave out fixed sequences of steps.
13. Matching the existing code is no reason to keep a poor pattern. Fix it, or flag it in the plan.
