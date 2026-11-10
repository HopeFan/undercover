import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Run } from "./api";
import { time } from "./format";
import { stubApi, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const startedAt = "2026-11-10T09:00:00+00:00";

const running: Run = {
  run_id: "run-1",
  cap: 5,
  started_at: startedAt,
  finished_at: null,
  todos: [
    { content: "Work CLM-1001", status: "done" },
    { content: "Work CLM-1002", status: "in_progress" },
    { content: "Work CLM-1003", status: "to_do" },
    { content: "Work CLM-1004", status: "left_for_handler" },
  ],
  summary: null,
};

function showQueue(run: Run | null) {
  const routes: Record<string, unknown> = {
    "GET /api/claims": [summary],
    "GET /api/runs/current": run,
  };
  stubApi(routes);
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  return routes;
}

async function runPanel() {
  const heading = await screen.findByRole("heading", { name: "Current run" });
  const panel = heading.closest("section");
  if (!panel) throw new Error("The run heading has no panel");
  return within(panel);
}

it("says when there's no run yet", async () => {
  showQueue(null);
  const panel = await runPanel();
  expect(await panel.findByText(/No run yet/)).toBeDefined();
});

it("shows a running run's to-do list with a chip for each status", async () => {
  showQueue(running);
  const panel = await runPanel();
  const list = await panel.findByRole("list", {
    name: "The agent's to-do list",
  });
  const items = within(list).getAllByRole("listitem");
  expect(items.map((item) => item.textContent)).toEqual([
    "DoneWork CLM-1001",
    "In progressWork CLM-1002",
    "To doWork CLM-1003",
    "Left for a handlerWork CLM-1004",
  ]);
  expect(within(items[3]).getByText("Left for a handler").className).toBe(
    "chip todo-left_for_handler",
  );
  expect(
    panel.getByText(
      `Running since ${time(startedAt)}, up to 5 claims. 1 of 4 done.`,
    ),
  ).toBeDefined();
  expect(panel.queryByRole("heading", { name: "Summary" })).toBeNull();
});

it("shows a finished run's summary", async () => {
  const finishedAt = "2026-11-10T09:05:00+00:00";
  showQueue({
    ...running,
    cap: 1,
    todos: [],
    finished_at: finishedAt,
    summary: "Worked 1 claim: 1 approve.",
  });
  const panel = await runPanel();
  expect(
    await panel.findByText(`Finished at ${time(finishedAt)}, up to 1 claim.`),
  ).toBeDefined();
  expect(
    panel.getByText("The agent hasn't planned its work yet."),
  ).toBeDefined();
  expect(panel.getByText("Worked 1 claim: 1 approve.")).toBeDefined();
});

it("fills in and ticks off the list as the run goes", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const routes = showQueue(null);
  const panel = await runPanel();
  expect(await panel.findByText(/No run yet/)).toBeDefined();

  routes["GET /api/runs/current"] = {
    ...running,
    todos: [{ content: "Work CLM-1001", status: "to_do" }],
  };
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(panel.getByText("To do")).toBeDefined();

  routes["GET /api/runs/current"] = {
    ...running,
    todos: [{ content: "Work CLM-1001", status: "done" }],
  };
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(panel.getByText("Done")).toBeDefined();
  expect(panel.queryByText("To do")).toBeNull();
});
