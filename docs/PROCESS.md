# Process

`uv sync` and `npm install` at the repo root install everything, including a git pre-commit hook. `npm run dev` starts the backend and the dashboard.

`npm run check` runs every check:

- Python: ruff (lint and format), pyright, and pytest with 80% coverage
- TypeScript: ESLint, Prettier, tsc, and vitest with 80% coverage
- Playwright end-to-end tests

The pre-commit hook runs the format, lint, type and unit test checks on every commit.

## Planning

When asked to plan, as in "Please plan the pilot", write the plan to `docs/PLAN.md` and write no code.

- Split the work into phases, usually 5 or 6, each building on the last.
- Give each phase detailed success criteria that you can verify yourself: tests that pass, commands and their output, API calls and their responses, and pages you check in the browser with the Playwright MCP server. Write each one as a checkbox.
- Cover how the code is organized as well as what it does: which module holds what, what imports what, and what is defined once. Check the design against `docs/CODE_STANDARDS.md` before you hand the plan over.
- Then stop and wait until you are asked to implement the plan.

## Implementing

When asked to implement the plan, as in "Please implement the plan for the pilot", build every phase in order without stopping. For each phase:

1. Build it, with tests.
2. Check every success criterion and fix whatever fails.
3. Get a fresh review (below) and fix every must-fix finding.
4. Tick off its criteria in `docs/PLAN.md` and update `docs/STATUS.md`.
5. Commit. The pre-commit hook runs the checks; if it fails, fix the problem and commit again.

When the last phase is done, run `npm run check` and report the results.

## Fresh review

Passing checks don't show that the design is good, and the agent that wrote the code is the worst judge of it. Before each commit, a reviewer that did not write the code reviews the diff: a subagent with a fresh context, or another coding agent. It works read only, doesn't open `data/evals/` and doesn't look at other branches.

It judges the change as a pull request on its way to production, against `docs/CODE_STANDARDS.md` and the plan, not against the style of the existing code. It answers with evidence: the import graph, every way the code calls an external service, where tools and run state live, framework features rebuilt by hand, whether agent instructions give goals or scripts, and repeated logic. It lists must-fix and should-fix findings with files and lines.

Fix every must-fix finding and check it before the commit. Fix each should-fix finding, or note it in `docs/STATUS.md` with the reason it stays.

## Rules

- Add tests with each change. Tests never call a model; use a stub model.
- Outside a plan, commit each change once you have checked it.
- Run `npm run check` before you hand work over.
- Never use `git commit --no-verify`.
- Never lower a threshold, turn off a rule or exclude a file to get a green run. If a rule looks wrong, stop and ask.
- Keep `docs/STATUS.md` up to date.
- Never push.
- Don't open `data/evals/` unless you're asked to.
- Everything must work on Windows: write `package.json` scripts as `uv run` commands or `.mjs` files.
