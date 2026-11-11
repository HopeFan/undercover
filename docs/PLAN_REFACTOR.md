# Plan: the refactor after the human review

This plan answers `HUMAN_REVIEW_HARNESS.md`, the review of the agent code after the harness build, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, the agent is four modules with one job each: `api.py` talks to the backend, `tools.py` holds every tool, `harness.py` runs the two agents, and `__main__.py` is the command line. Run state reaches the tools through LangChain's `context_schema` and `ToolRuntime`. The instructions give each agent a goal and its limits instead of a script. The agent behaves as it does today, apart from two fixes the reviews found. The rules that would have caught all of this are in `CODE_STANDARDS.md` and `PROCESS.md`.

## The issues, confirmed

Each issue in the review was checked against the code on `week1day5-ehesami`:

1. **Hard-coded URLs and two ways to call the backend: confirmed.** There are 20 `/api/...` paths across `main.py` (6), `queue.py` (6) and `tools.py` (8). The backend is called through `tools.request()` with `tools.reply()`, and through `main.call_backend()`. `main.py` imports `request` from `tools.py`.
2. **Module organization: confirmed.** `queue.py` imports `main` and calls `main.call_backend`, `main.model` and `main.work_claim`. There is no `api` module.
3. **The harness spread out and mixed with UnderCover specifics: confirmed.** The harness is split across `main.py` and `queue.py`, and the same streaming loop is written twice, in `run()` and `converse()`. The queue's tools are closures inside `queue.py`, sharing a mutable `started` list, so the tools are not in one place. `work_queue` creates the run, builds the agent, sends reminders, handles a failure and writes the summary.
4. **Prescriptive instructions: confirmed.** `claim.md` is 9 numbered steps in 795 words, and `queue.md` is 6 numbered steps in 436 words.

Two more problems from the Codex reviews are fixed along the way:

- `--cap 0` is treated as no cap and works the whole queue (`queue.py:99`).
- The claim agent's tools take the claim id, policy id and customer id from the model. A claim's text comes from the customer, so a planted instruction could point the agent at another claim or another customer's records. The manual's section 11 says a customer's data is used only for that customer's claims.

## How this was allowed to happen

- **The pilot's patterns were extended, not questioned.** `main.py` importing `request` from `tools.py`, and `call_backend` beside `reply`, came from the pilot. The harness build added to them, and "consistent with the existing code" was taken to mean "good".
- **The standards said nothing about design.** `CODE_STANDARDS.md` has six rules, none about module boundaries, one client per service, using the framework's own features or how to write agent instructions. Ruff, pyright, the tests and coverage cannot see any of these.
- **The plan specified behavior, not structure.** `PLAN_HARNESS.md` had 57 detailed criteria for what the code does and none for how it is organized.
- **No independent review.** The coding agent that wrote the code was its only reviewer, and when asked, it called the code clean. Codex's built-in review, run afterwards, looks for defects, and none of these issues is a defect.

## Choices to review

1. **Standards and process first.** Phase 1 writes the new rules, so phases 2 to 6 are built and reviewed under them.
2. **A fresh reviewer before each commit.** After each phase's checks pass, a subagent that has not seen the work reviews the phase's diff against `CODE_STANDARDS.md`, read only. Its must-fix findings are fixed before the commit. Codex reviews the finished refactor with `community_contributions/erfan_hesami/week1day5_codex_review/review-prompt.md`, unchanged, as a second opinion from another model.
3. **Every claim tool works on the context's claim.** The claim agent's tools take no ids: `get_claim()`, `get_policy()`, `get_claim_history()`, `record_decision(decision, payout, section, reason)` and `pay_claim(amount)` act on the claim in the run's context. `list_sections` and `read_section` keep their arguments.
4. **The queue's tool calls the claim agent through its context.** `RunContext` carries the function that works a claim, so `tools.py` does not import `harness.py`, and tests can pass a stand-in.
5. **The module is still called `harness.py`**, not `main.py`, as the review asks, and `main.py` and `queue.py` go.

## Design

### Modules

```
__main__.py ──> harness.py ──> tools.py ──> api.py ──> the backend
                    │                          ▲
                    └──────────────────────────┘
```

- `api.py`: the backend's address, defined once, and one function per backend operation, named after it, such as `api.record_decision(claim_id, ...)`. A refusal raises `ApiError` with the status and the backend's reason. Nothing else in `agent/` builds a URL or makes an HTTP request.
- `tools.py`: every tool for both agents, and the two contexts. `ClaimContext` holds the claim id, policy id and customer id, and never changes. `RunContext` holds the run id, the cap, the function that works a claim and the claims started so far. Each tool takes `runtime: ToolRuntime[...]` where it needs the context, and calls `api.py`. The claims started are the one thing a tool changes. They stay in the context rather than the graph's state, because each tool call runs on its own and parallel calls reading state could pass the cap.
- `harness.py`: the model, the middleware, one function that streams an agent and hands each new message to a callback, the claim agent with `work_claim`, and the queue agent with `work_queue`, split into small functions. It imports `api` and `tools`, and nothing imports it but `__main__.py`.

### Errors

LangChain's `ToolErrorMiddleware` returns an `ApiError` to the model as an error `ToolMessage`, so the model sees the backend's refusal as it does today, and any other exception still stops the attempt and is put right by `work_claim`. `ToolRetryMiddleware` retries only connection errors and timeouts, never a refusal. `tools.reply()`, `REFUSED`, `main.call_backend()` and the check for text starting "Refused" all go. A failed `read_section` is recognized by its message's error status.

### Instructions

Each file states the goal first, then what the agent has to work with, then its limits, with no numbered workflow:

- `claim.md`: decide this claim as an experienced UnderCover handler would, with the right decision, payout and reason. The wording comes first and the manual covers what it leaves open, and the agent finds and reads the sections the claim needs. The limits: one decision, refer only for the manual's reasons, an approval over the limit waits for sign-off, and a one-line reply at the end.
- `queue.md`: work the waiting claims up to the cap, keeping the team's to-do list current, and finish with a short summary for the handlers. The limits: hand each claim to `work_claim`, never decide or pay a claim, give a claim that comes back to the queue one more try, and write the summary as one plain paragraph.

### How the criteria are checked

As in `PLAN_HARNESS.md`. Live runs use `npm run dev` on port 8000 after reseeding, capped at five claims. While another project holds port 8001, the e2e tests run from a scratch copy of `playwright.config.ts` on ports 8011 and 5184.

## Phase 1: Standards and process

Write the rules that would have caught the review's issues. No code changes.

- [x] `CODE_STANDARDS.md` adds rules for one module per external service with its address defined once, modules that use each other only through their public functions, all tools in one module with run state through the framework's context, the framework's own features before hand-made ones, no repeated logic, and agent instructions written as a goal and limits rather than steps
- [x] `PROCESS.md` adds the fresh review before each commit: who reviews, what they review against, and that must-fix findings are fixed before the commit. A plan's success criteria cover how the code is organized as well as what it does
- [x] `STATUS.md` says the refactor is in progress
- [x] `npm run check` passes

## Phase 2: One API module

Add `agent/api.py` and move every backend call into it. Use `ToolErrorMiddleware` for refusals, and limit `ToolRetryMiddleware` to connection errors and timeouts.

- [x] `grep -rn "/api/" agent --include=*.py` finds backend paths only in `agent/api.py` and the tests. The one other match is OpenRouter's address, which belongs to the model and is defined once where the model is set up
- [x] `grep -rn "localhost:8000" agent` finds the address once, in `agent/api.py`
- [x] `grep -rnE "def (request|reply|call_backend)|REFUSED" agent` finds nothing
- [x] pytest: each `api` function calls its backend operation, and a refusal raises `ApiError` with the status and reason
- [x] Stub model test: a payment over the limit still reaches the model as an error message that mentions sign-off, and the run carries on
- [x] Stub model test: an unknown section still reaches the model as an error message, with no Read step
- [x] Stub model test: a refusal is not retried, and a connection error is retried twice
- [x] Every behavior test from the harness build passes
- [x] The fresh review finds no must-fix issue
- [x] `npm run check` passes

## Phase 3: All the tools in one place, with run state through the context

Move the queue's tools into `agent/tools.py`, add `ClaimContext` and `RunContext`, and give every tool that needs them `runtime: ToolRuntime[...]`. Fix `--cap 0`.

- [x] `agent/tools.py` holds all ten tools, and `grep -rn "@tool" agent --include=*.py` finds no other module outside the tests
- [x] A pytest test checks the claim agent's tool schemas: no tool has a `claim_id`, `policy_id` or `customer_id` argument
- [x] Stub model test: the claim agent records its decision and payment on the claim in its context, and a stub that asks for another claim has no way to name it
- [x] Stub model test: the cap, the to-do list, a failed claim going back in the queue and being tried again, a claim that fails twice, and the missed-claims check all behave as in the harness build, with the run's state in `RunContext`
- [x] `uv run -m agent --cap 0` exits with a message that the cap must be at least 1, and starts no run. A negative cap does the same
- [x] `queue_tools()` and its closures are gone: `grep -rn "def queue_tools" agent` finds nothing, and the queue's tools read the run id, the cap and the claims started from `runtime.context`
- [x] The fresh review finds no must-fix issue
- [x] `npm run check` passes

## Phase 4: One harness module

Replace `agent/main.py` and `agent/queue.py` with `agent/harness.py`. Write the streaming loop once, and split `work_queue` into small functions.

- [x] `ls agent/*.py` lists exactly `__init__.py`, `__main__.py`, `api.py`, `harness.py` and `tools.py`
- [x] Imports: `api.py` imports no other agent module, `tools.py` imports only `api`, and only `__main__.py` imports `harness`
- [x] One function in `harness.py` calls `.stream(`, and both agents use it
- [x] No function in `agent/`, outside the tests, is longer than 30 lines, checked with a short script
- [x] The retry counts, the call limits and the reminders are named constants
- [x] Every behavior test from the harness build passes, moved to the new modules
- [x] The fresh review finds no must-fix issue
- [x] `npm run check` passes

## Phase 5: Instructions as goals

Rewrite `backend/instructions/claim.md` and `queue.md` as a goal, what the agent has to work with, and its limits. Write them from the policy wording and the manual, never from `data/evals/`.

- [ ] Neither file has a numbered workflow, and each opens with its goal
- [ ] Every rule in today's instructions is still there or deliberately dropped, listed in the commit message: the wording first, refer only for the manual's reasons, one decision, sign-off over the limit, the summary as one plain paragraph, and a referral counted as done
- [ ] Each file is shorter than today's
- [ ] Live: on a fresh database, `uv run -m agent CLM-1020` prints one line, and its steps include Read steps for the manual's interpretation notes
- [ ] The fresh review finds no must-fix issue
- [ ] `npm run check` passes

## Phase 6: The backend and dashboard, a live trial and the docs

Apply the same review to `backend/` and `dashboard/`, fix what it confirms, run the trial and update the docs.

- [ ] Each candidate is confirmed or ruled out, and the fixes are made. Three are known: the backend repeats a "find a row or return 404" lookup 7 times, status names appear as text in SQL in 6 places, and the harness's `settle` pays an approval the agent left unpaid, a business action that may belong in the backend. The dashboard already has one client in `api.ts`. The findings are listed in `STATUS.md`
- [ ] Live: after reseeding, `uv run -m agent --cap 5` works five claims on its own. The queue page shows the to-do list filling in and being ticked off, and each claim page shows its Read steps. The other claims stay waiting, and none is in progress
- [ ] Live: every approval within the limit is paid once, and every approval over $1,000 waits for sign-off with no payment
- [ ] Live: the five decisions are compared with the last trial's (approve CLM-1001 $420.00, CLM-1008 $2,240.00 and CLM-1011 $1,150.00, refer CLM-1018, decline CLM-1010), and any difference is reported
- [ ] Codex reviews the finished code with `review-prompt.md`, unchanged and read only, and its findings are scored against the rubric in that folder and reported
- [ ] `SPEC.md`, `TECH_STACK.md` and `STATUS.md` describe the product as it now is
- [ ] `npm run check` passes

## Not in this plan

- Scoring the decisions against `data/evals/`, which the process says to open only when asked. The trial compares them with the last trial instead.
- Any new feature from a later brief.
- Changing the backend's API or the dashboard's pages, other than fixes the review in phase 6 confirms.
