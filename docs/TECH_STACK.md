# Tech stack

- `backend/`: FastAPI and SQLite. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount.
- `agent/`: LangChain's `create_agent` on OpenRouter, with LangChain's built-in middleware for retries and call limits, and no other agent framework. Four modules: `api.py` is the only backend client, `tools.py` holds every tool with run state through LangChain's `context_schema` and `ToolRuntime`, `harness.py` runs the agents, and `__main__.py` is the command line. A queue agent works a run and hands each claim to a claim agent on a fresh thread. There are two entry points: `work_queue(cap)` for a run and `work_claim(claim_id)` for one claim. It reaches claims, runs, its instructions, the policy wording and the claims manual only through the backend's API, at `UNDERCOVER_API` or port 8000. It uses `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
