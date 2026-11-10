# Status

The claims pilot in `docs/PLAN.md` is built: all six phases are done. The harness in `docs/PLAN_HARNESS.md` is being built: phase 1 of 5 is done.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
- `uv run -m backend.seed` rebuilds the database from `data/`, putting every claim back in the queue.
- `uv run -m agent` works every waiting claim in queue order and prints each decision, then a count. `uv run -m agent CLM-1001` works one claim and prints the agent's reply. Both use the real model through OpenRouter.

## Built

- `backend/`: SQLite database seeded from `data/` (never `data/evals/`), at `undercover.db` or the path in `UNDERCOVER_DB`, created on startup when missing. The policy wording and the claims manual are stored as numbered sections, split at their `## ` headings. Read operations: `health`, `list_claims`, `get_claim`, `get_policy`, `get_claim_history`, `list_handlers`, `list_steps`, `get_instructions`, `list_sections`, `read_section`. Workflow operations: `start_claim`, `record_step`, `record_decision`, `pay_claim`, `sign_off_claim`. A claim moves from waiting to in progress to decided, or to waiting for sign-off when an approval pays over the limit in `company.json`. `pay_claim` refuses such a payout with a 403 until a handler signs off, and signing off pays it. The agent's instructions for working a claim are in `backend/instructions/claim.md`, and `get_instructions` serves them. A test checks that every operation follows the API rules.
- `agent/`: `run(claim_id, thread_id)` starts the claim, fetches its instructions from the backend and works the claim with seven tools named after backend operations: `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `read_section`, `record_decision` and `pay_claim`. It records every tool call, tool result and message as a step, and each section it reads as a `read` step. `work_queue()` runs it on each waiting claim, and reports a failed claim and moves on. The default model is `deepseek/deepseek-v4.1-flash` with low reasoning effort.
- `dashboard/`: the queue (`/`), with counts by state and a line per claim. A claim in full (`/claims/:claimId`), with its policy, earlier claims, the decision and payment, the agent's steps as it works, including the sections it read, and a sign-off form for a held payout. The agent's instructions (`/instructions`), read only. The queue and a claim page refresh every two seconds. Styled to `BRAND.md` in light and dark mode.
- `e2e/`: tests of the three pages, the agent's steps appearing on a claim page, and a handler signing off a held payout. Playwright runs its own backend on port 8001 with `e2e/undercover.db`, and its own dashboard on port 5174, so it can run next to `npm run dev`.

## Last live runs

On September 27, 2026, `uv run -m agent` with `openai/gpt-6-luna` worked all 25 claims in 2 minutes 47 seconds: 17 approve, 5 decline and 3 refer. Three approvals were over $1,000 and waited for sign-off (CLM-1003, CLM-1008 and CLM-1011), and every other approval was paid its payout. These decisions have not yet been scored against the handlers' decisions in `data/evals/`.

On November 10, 2026, `uv run -m agent CLM-1020` with `deepseek/deepseek-v4.1-flash` worked the claim in 48 seconds. It read four sections of the wording and five of the manual, including the manual's interpretation notes, and approved $240.00, which was paid.
