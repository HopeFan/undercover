# Plan: the harness

This plan builds the brief in `HARNESS.md` on top of the finished pilot, in five phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, one command works the queue. A queue agent plans the run as a to-do list, hands each claim to a fresh claim agent, and finishes with a summary for the handlers. The claim agent looks up the sections of the policy wording and the claims manual it needs, instead of being handed the whole wording. Failures are retried, a claim that fails twice is left for a handler, and nothing is ever decided or paid twice. The queue page shows the run's to-do list as it fills in and is ticked off.

## Choices to review

These are the choices the brief leaves open. Each one is explained further down.

1. **Our own to-do list, not LangChain's `TodoListMiddleware`.** LangChain's version keeps the list inside the agent's memory, where the dashboard can't see it, and it has three statuses with no "left for a handler". We need four statuses, and we need the list stored in the backend. So `write_todos` is our own tool, and it calls a backend operation of the same name.
2. **The subagent is a plain tool.** `work_claim` runs our existing claim agent on a new thread and returns one line. That is what Deep Agents' `task` tool does in Lab 2, built into our own agent as the brief asks.
3. **Code enforces the cap and the missed-claims check, and the instructions also ask for them.** The instructions tell the queue agent to stay within its cap and to check the queue before it finishes. The harness refuses a claim beyond the cap. If the agent stops while waiting claims remain within its cap, the harness reminds it, up to twice. A model can forget an instruction, but it can't get past the code.
4. **The harness completes a payment the agent didn't make.** An approval within the limit can be left unpaid, either because the model forgot or because a failure came between the decision and the payment. In that case the harness pays the approved payout. The backend still allows only one payment.
5. **A stopped run doesn't leave claims stuck.** A run can be stopped partway, with Ctrl+C or a closed terminal. When the next run starts, it counts any claim still in progress as a failed attempt and puts it back in the queue.
6. **No `BACKEND_URL` after all.** The draft of this plan added it because another project seemed to hold port 8000. It turned out to be UnderCover's own `npm run dev`, which reloads as the code changes, so the live checks use it as it is.

## Design

### How a run works

```
uv run -m agent --cap 5
  start_run            the backend opens a run; a claim left in progress goes back to waiting
  queue agent          list_claims -> write_todos -> work_claim -> write_todos -> ... -> summary
    work_claim         a fresh claim agent on a new thread works one claim and reports one line:
                       "CLM-1004  approve  $215.00", or "CLM-1007  failed: ... Back in the queue."
  missed-claims check  waiting claims within the cap? remind the queue agent (at most twice)
  finish_run           the backend stores the summary, which the queue page shows
```

`uv run -m agent` works every waiting claim, and its cap is the number of claims waiting when it starts. `uv run -m agent --cap 5` works at most five claims. `uv run -m agent CLM-1001` works one claim with `work_claim` and prints its line, with no run and no to-do list.

### Claim states

One new state joins the four from the pilot:

| State | Meaning | Label on screen | Color |
| --- | --- | --- | --- |
| `left_for_handler` | The agent failed on it twice before deciding it | Left for a handler | Raspberry, white text |

A claim that fails moves `in_progress` → `waiting` on its first failure and `in_progress` → `left_for_handler` on its second. Each claim keeps a count of its failures, and only reseeding resets it.

### Database

- `sections`: the policy wording and the claims manual, split at their `## ` headings when the database is seeded. Each row holds the document (`policy_wording` or `claims_manual`), the section number, the title and the text. The wording no longer sits in `settings`.
- `claims` gains `failures`, starting at 0.
- `runs`: the run id, the cap, start and finish times, the to-do list as JSON text, and the summary.
- Steps gain two kinds. `read` is a section the agent read. `error` is a failed attempt and what went wrong.

### API

New and changed operations. They follow the same rules as before: an `operation_id`, a one-line docstring and no optional inputs.

| Operation | Route | What it does |
| --- | --- | --- |
| `list_sections` | `GET /api/documents/{document}/sections` | The contents of `policy_wording` or `claims_manual`: each section's number and title |
| `read_section` | `GET /api/documents/{document}/sections/{section}` | One section's title and text |
| `fail_claim` | `POST /api/claims/{claim_id}/failure` | Body `{error}`. For a claim in progress: adds an `error` step, counts the failure, and moves the claim back to waiting, or to left for a handler on its second failure |
| `start_run` | `POST /api/runs` | Body `{run_id, cap}`. Opens a run. Any claim still in progress is failed as above, with the error "The run working this claim was stopped" |
| `write_todos` | `PUT /api/runs/{run_id}/todos` | Body `{todos}`, a list of `{content, status}`. Replaces the run's to-do list |
| `finish_run` | `POST /api/runs/{run_id}/finish` | Body `{summary}`. Records the summary and the finish time |
| `get_current_run` | `GET /api/runs/current` | The latest run, with its to-do list and summary, or null before the first run |
| `get_instructions` | `GET /api/instructions` | Now `{queue, claim}`: the two sets of instructions, with no policy wording added |

Rules the backend enforces:

- `fail_claim` needs a claim in progress (409 otherwise). A decided claim can never be sent back to the queue, so it can't be decided twice. The existing rules still block a second decision or payment.
- A to-do status is `to_do`, `in_progress`, `done` or `left_for_handler`, and its content can't be empty (422 for each). A run id that's already used returns 409. An unknown run, document or section returns 404. `get_current_run` returns null before the first run rather than a 404, because the dashboard stops refreshing on a 404, and a queue page opened before a run starts must still see it begin.

### The claim agent

The pilot's agent becomes the claim agent. It still lives in `agent/main.py` and records every step on its claim.

- **Tools.** It has seven: `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `read_section`, `record_decision` and `pay_claim`. Each is named after the backend operation it calls. A section it reads is recorded as a `read` step, such as `Claims manual, section 9: Repeat claims`, with the section's text after it.
- **Middleware.** LangChain's built-in middleware handles problems inside one attempt:
  - Each model call times out after 60 seconds.
  - `ModelRetryMiddleware` retries a failed model call up to 3 times, waiting longer each time.
  - `ToolRetryMiddleware` retries a backend call that fails to connect or times out. A refusal from the backend still goes back to the model as text, as in the pilot.
  - `ModelCallLimitMiddleware` stops an attempt after 30 model calls. A normal claim takes about 12.
- **`work_claim(claim_id)`.** This harness function is used by the queue agent's tool and by the command line. It runs the claim agent on a new thread id and returns one line:
  - `CLM-1001  approve  $420.00`
  - `CLM-1008  approve  $1,500.00  waiting for sign-off`
  - `CLM-1007  failed: <error>. Back in the queue.` or `... Left for a handler.`

  A claim that raises an error, or finishes without a decision, goes to `fail_claim`. An approval within the limit that's left unpaid is paid by the harness.
- **Model.** The default is `deepseek/deepseek-v4.1-flash` with low reasoning effort. `MODEL_NAME` overrides it, as before.

### The queue agent

This is a new `create_agent` in `agent/queue.py`.

- **Tools.** It has three:
  - `list_claims`, the backend operation.
  - `write_todos`, which stores the list for this run.
  - `work_claim`, which hands one claim to a fresh claim agent. It refuses with "This run is capped at 5 claims" once the run has started five different claims. A retry of a claim already started doesn't count against the cap.
- **Its prompt.** It is told "Work the waiting claims in the queue, up to 5 claims." The order is up to the agent.
- **Middleware.** `ModelRetryMiddleware` retries a failed model call. `ModelCallLimitMiddleware` ends the run after 4 model calls per claim in the cap, plus 10.
- **The missed-claims check.** When the queue agent replies, the harness looks for waiting claims that are still within the cap. These are claims the run started that came back to the queue, plus any claims the run hasn't started yet, if there's still room under the cap. If there are any, the harness names them in a message on the same thread and lets the agent carry on. It does this at most twice.
- **The summary.** The agent's last reply is the summary. `finish_run` stores it, and the command line prints it after the line for each claim.

### Putting problems right

| Problem | What happens |
| --- | --- |
| The model provider errors or times out | The call is retried up to 3 times |
| A backend call can't connect or times out | The call is retried up to twice |
| A claim agent goes round in circles | It is stopped after 30 model calls, and that counts as a failure |
| A claim fails before it is decided | An error step goes on the claim, and the claim goes back in the queue to be tried again |
| The same claim fails a second time | It is left for a handler |
| A failure comes after the decision | The claim stays decided. It is never sent back, decided again or paid twice. An unpaid approval within the limit is paid by the harness |
| The run is stopped partway | The next run puts any claim still in progress back in the queue |
| The queue agent stops early | The missed-claims check reminds it |

### Instructions

They are written from the policy wording and the manual, never from `data/evals/`. `backend/instructions.md` becomes two files.

- **`backend/instructions/claim.md`, working a claim.** It follows the order in section 4 of the manual.
  - Read the claim, the policy and the history.
  - Look at the contents of both documents, then read the sections the claim needs. That is always section 1 (the plan's limits) and the benefit's section of the wording, then the manual's sections on documents (5) and repeat claims (9). Read the interpretation notes (7) and any other section when the claim touches them.
  - The wording comes first, and the manual covers what it leaves open.
  - Record one decision, naming the section relied on, which can be a section of the manual. Pay an approval.
  - Finish with one line.
- **`backend/instructions/queue.md`, running the queue.**
  - List the queue and plan the waiting claims, up to the cap, as a to-do list with one item per claim.
  - Mark an item in progress before handing its claim to `work_claim`. Mark it done, or left for a handler, from the line that comes back. A claim that comes back to the queue stays to do and is tried again.
  - Work one claim at a time, and never decide a claim yourself.
  - Before finishing, list the queue again and check that no waiting claim within the cap was missed.
  - End with a short summary for the handlers: what was decided, which payouts wait for sign-off, and which claims were left for a handler and why.

### Dashboard

- **The queue page** gets a fifth tile, Left for a handler. A Current run panel sits above the table:
  - whether the run is running or finished, its start time and its cap
  - the to-do list, each item with a status chip: To do in Cerulean, In progress in Marigold, Done in Sea Green, Left for a handler in Raspberry
  - the summary once the run finishes

  It shows "No run yet" before the first run. It refreshes every two seconds, like the queue.
- **The claim page's steps** show a `read` step as "Read" with the section's name, and its text folds open on click. They show an `error` step as "Failed" with what went wrong. A claim left for a handler says so in the decision panel.
- **The instructions page** shows two panels: Running the queue and Working a claim. Its lead says the agent looks up the wording and the manual as it needs them.

### How the criteria are checked

As in the pilot, API calls run against the dev servers on a freshly seeded database. Pages are checked in the browser with the Playwright MCP server, and tests never call a model. Only criteria marked "Live" use the real model, and a live queue run is always reseeded first and capped at five claims.

On this machine, port 8001 is held by another project, so `npm run e2e` can't start its own backend there. Until that's free, the e2e tests run from a scratch copy of `playwright.config.ts` that uses ports 8011 and 5184, with the same tests and a fresh database.

## Phase 1: The claims manual, looked up the way a handler would

Seed the wording and the manual as sections. Add `list_sections` and `read_section`, and give the claim agent the two lookup tools and `read` steps. Rewrite the claim instructions as `backend/instructions/claim.md`. `get_instructions` keeps its `{text}` shape for now, serving those instructions without the wording. Make DeepSeek V4.1 Flash the default model. Show `read` steps on the claim page, and update the manual's place in `SPEC.md` and the model in `TECH_STACK.md`.

- [x] `curl -s localhost:8000/api/documents/claims_manual/sections` returns 14 sections in order, the ninth being `Repeat claims`. The same for `policy_wording` returns 12, the tenth being `How we work out your payment`
- [x] `curl -s localhost:8000/api/documents/claims_manual/sections/10` returns the title `Meals without receipts` and text that includes `$35 per traveler`
- [x] An unknown document and an unknown section each return 404
- [x] A pytest test checks that each section's text matches the file from its heading to the next one
- [x] `curl -s localhost:8000/api/instructions` returns the claim instructions, and they don't include the wording's title `# UnderCover Travel Insurance: Policy Wording`
- [x] A pytest test checks that the claim agent's tools are exactly the seven above, each named after a backend operation
- [x] Stub model test: the stub reads `claims_manual` section 9, then decides and pays. The claim is `decided` and paid, and its steps include a `read` step that starts `Claims manual, section 9: Repeat claims`
- [x] Stub model test: a `read_section` for an unknown section reaches the model as a refusal, and the run carries on
- [x] `model()` uses `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, and the model in `MODEL_NAME` when it's set
- [x] vitest: a `read` step shows "Read" and the section's name, and its text is folded until clicked
- [x] `grep -rn evals backend agent dashboard/src` finds nothing, and `grep -rn "data/" agent` finds nothing
- [x] Live: on a fresh database, `uv run -m agent CLM-1020` (sunglasses taken by a monkey) prints a reply. `curl -s localhost:8000/api/claims/CLM-1020/steps` then shows `read` steps for the sections it read, including the manual's section 7, Interpretation notes
- [x] Live, in the browser: `/claims/CLM-1020` shows those Read steps, and `/instructions` shows the new claim instructions
- [x] `docs/SPEC.md` says decisions follow the policy wording and the claims manual, and the manual is no longer under "Not for now". `docs/TECH_STACK.md` names the new default model
- [x] `npm run check` passes

## Phase 2: Putting a failed claim right

Add `fail_claim`, the failure count, the `left_for_handler` state and `error` steps. Add the claim agent's middleware and model timeout. Build `work_claim()`, and make `uv run -m agent CLM-1001` print its one line. On the dashboard, add the fifth state, the Failed steps and the decision panel's note for a claim left for a handler.

- [x] pytest: `fail_claim` on a claim in progress adds an `error` step, moves the claim to `waiting` and counts one failure. On the same claim's second failure it moves the claim to `left_for_handler`
- [x] pytest: `fail_claim` on a claim that's waiting, decided or waiting for sign-off returns 409 and changes nothing. `start_claim` on a claim left for a handler returns 409
- [x] Stub model test, failure and retry: the first attempt's stub raises an error after reading the claim. `work_claim` returns a line ending `Back in the queue.` and the claim is `waiting`. A second `work_claim` with a good stub decides it. The steps hold both attempts under two thread ids, with the `error` step between them
- [x] Stub model test, two failures: the claim is `left_for_handler` and the line ends `Left for a handler.`
- [x] Stub model test, a model call that fails once and then succeeds: `ModelRetryMiddleware` retries it, and the claim is decided with no failure recorded
- [x] Stub model test: a stub that never stops calling tools is stopped by the call limit and counted as a failure
- [x] Stub model test, failure after the decision: the stub approves $420.00 and then raises. The claim stays `decided` with one decision, and the harness pays $420.00 once. A further `work_claim` on it returns a line saying it isn't waiting, and nothing changes
- [x] Stub model test: a stub that finishes without recording a decision counts as a failure
- [x] `uv run -m agent CLM-1001` prints the one line from `work_claim` (tested with `work_claim` stubbed)
- [x] vitest: the Left for a handler tile and chip, a Failed step, and the decision panel's note for a claim left for a handler
- [x] Browser, with `browser_evaluate`: the Left for a handler chip has the Raspberry background `#EF476F` and white text
- [x] Live: on a fresh database, `uv run -m agent CLM-1001` prints one line with the decision and payout
- [x] `npm run check` passes

## Phase 3: Runs and the to-do list on the queue page

Add the `runs` table and `start_run`, `write_todos`, `finish_run` and `get_current_run`. Add the Current run panel to the queue page. No agent changes yet. The e2e test stands in for the queue agent, as the pilot's tests stood in for the claim agent.

- [x] pytest: `start_run` opens a run, and the same run id again returns 409
- [x] pytest: `start_run` fails a claim left in progress. The claim goes back to `waiting` with an `error` step saying the run was stopped, or to `left_for_handler` on its second failure
- [x] pytest: `write_todos` replaces the list. An unknown status or empty content returns 422, and an unknown run returns 404
- [x] pytest: `finish_run` records the summary and finish time. `get_current_run` returns the latest run, and null before the first one
- [x] The OpenAPI test passes with the new operations
- [x] vitest: the panel with no run yet, with a running run whose items have each status chip, and with a finished run and its summary. With fake timers, it refreshes as the list changes
- [x] e2e: the test starts a run and writes three to-do items. Without a reload, the queue page shows them as To do, then one as In progress and one as Done, then the summary after `finish_run`
- [x] Browser, with `browser_evaluate`: each to-do chip has the color from the design. Screenshots of the panel in light and dark mode show rounded panels with no outlines
- [x] Browser: `browser_console_messages` shows no errors on the queue page, with or without a run
- [x] `npm run check` passes

## Phase 4: The queue agent

Build the queue agent in `agent/queue.py` with its three tools, middleware, the cap, the missed-claims check and the summary. Write `backend/instructions/queue.md`, and change `get_instructions` to `{queue, claim}`, with the instructions page showing both. Add `--cap` to the command line.

- [ ] A pytest test checks that the queue agent's tools are exactly `list_claims`, `write_todos` and `work_claim`
- [ ] Stub model test, the to-do list stored: the queue stub writes a list, works its claims and updates the list. `get_current_run` holds each version as it is written, and finally every item is `done`
- [ ] Stub model test, the cap: with a cap of 2, the stub's third `work_claim` is refused with the cap message. That claim stays `waiting`, and the run shows cap 2
- [ ] Stub model test, a failed claim doesn't stop the run: the claim stub raises on CLM-1002. CLM-1001 and CLM-1003 are still decided, and the run finishes with a summary
- [ ] Stub model test, back in the queue and tried again: CLM-1002 fails once, the queue stub calls `work_claim` on it again, and it's decided
- [ ] Stub model test, two failures: CLM-1002 is `left_for_handler`, and its to-do item is `left_for_handler`
- [ ] Stub model test, the missed-claims check: with a cap of 2, the stub replies after working one claim. The harness's reminder names one waiting claim, the stub works it, and the claim is decided. A claim beyond the cap stays `waiting`. With nothing missed, no reminder is sent, and after two reminders the run finishes anyway
- [ ] `uv run -m agent --cap 5` prints a line per claim, then the summary (tested with stubs)
- [ ] `curl -s localhost:8000/api/instructions` returns `queue` and `claim`
- [ ] vitest and e2e: the instructions page shows Running the queue and Working a claim
- [ ] `grep -rn evals backend agent dashboard/src` finds nothing
- [ ] `npm run check` passes

## Phase 5: A live trial and the docs

Run the brief's trial and bring the docs up to date.

- [ ] Live: after `uv run -m backend.seed`, with the queue page open, `uv run -m agent --cap 5` works five claims on the default model with no help
- [ ] Live, in the browser: snapshots taken during the run show the to-do list filling in and being ticked off. At the end, the Current run panel shows the summary
- [ ] Live: afterwards, `curl -s localhost:8000/api/claims` shows five claims worked and 20 still `waiting`, with none `in_progress`
- [ ] Live: every approval within the limit is paid exactly its payout, once, and every approval over $1,000 is `waiting_for_sign_off` with no payment
- [ ] Live, in the browser: each of the five claim pages shows its steps, including Read steps for the sections the agent read
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is. `STATUS.md` records the trial's time and outcomes
- [ ] `npm run check` passes

## Not in this plan

- Scoring the agent against the handlers' decisions in `data/evals/`, which the process says to open only when asked.
- Working claims in parallel. The queue agent works one claim at a time.
- Starting a run from the dashboard, or a handler putting a claim left for a handler back in the queue.
- Summarizing the queue agent's conversation. Each claim adds one short line to it, so even a full queue of 25 stays small.
