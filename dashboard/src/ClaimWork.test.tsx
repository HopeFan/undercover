import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Claim, Decision, Handler, Step } from "./api";
import { Refusal, claim, history, policy, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const decidedAt = "2026-09-27T17:06:16+00:00";

const handlers: Handler[] = [
  {
    handler_id: "HND-01",
    name: "Dana Whitfield",
    role: "Senior Claims Handler",
    can_approve_over_limit: true,
  },
  {
    handler_id: "HND-04",
    name: "Sam Trainee",
    role: "Trainee",
    can_approve_over_limit: false,
  },
];

const steps: Step[] = [
  {
    step_id: 1,
    thread_id: "t-1",
    kind: "tool_call",
    content: 'get_claim(claim_id="CLM-1002")',
    created_at: decidedAt,
  },
  {
    step_id: 2,
    thread_id: "t-1",
    kind: "tool_result",
    content: `get_claim: {"claim_id":"CLM-1002","story":"${"A long story. ".repeat(10)}"}`,
    created_at: decidedAt,
  },
  {
    step_id: 3,
    thread_id: "t-1",
    kind: "read",
    content:
      "Claims manual, section 9: Repeat claims\n\nBefore deciding any claim.\n\nMost third claims are paid.",
    created_at: decidedAt,
  },
  {
    step_id: 4,
    thread_id: "t-1",
    kind: "message",
    content: "Approved and paid.",
    created_at: decidedAt,
  },
];

function showClaim(shown: Claim, stepsShown: Step[] = []) {
  const routes: Record<string, unknown> = {
    "GET /api/claims/CLM-1002": shown,
    "GET /api/claims/CLM-1002/steps": stepsShown,
    "GET /api/policies/POL-2002": policy,
    "GET /api/customers/CUS-3002/claims": history,
    "GET /api/handlers": handlers,
  };
  const fetchMock = stubApi(routes);
  render(
    <MemoryRouter initialEntries={["/claims/CLM-1002"]}>
      <App />
    </MemoryRouter>,
  );
  return { routes, fetchMock };
}

async function decisionPanel() {
  const heading = await screen.findByRole("heading", { name: "Decision" });
  const panel = heading.closest("section");
  if (!panel) throw new Error("The decision heading has no panel");
  return within(panel);
}

const approval: Decision = {
  decision: "approve",
  payout: 420,
  section: "Section 5, Baggage and Personal Effects",
  reason: "The suitcase was lost by the carrier.",
  decided_at: decidedAt,
};

const approved: Claim = {
  ...claim,
  status: "decided",
  thread_id: "t-1",
  decision: approval,
  payment: { amount: 420, paid_at: decidedAt, signed_off_by: null },
};

const held: Claim = {
  ...approved,
  status: "waiting_for_sign_off",
  decision: { ...approval, payout: 1350 },
  payment: null,
};

it("says when the agent hasn't started", async () => {
  showClaim(claim);
  const panel = await decisionPanel();
  expect(
    panel.getByText("The agent hasn't started on this claim."),
  ).toBeDefined();
  expect(await screen.findByText(/No steps yet/)).toBeDefined();
});

it("says when the agent is working", async () => {
  showClaim({ ...claim, status: "in_progress", thread_id: "t-1" });
  const panel = await decisionPanel();
  expect(panel.getByText("The agent is working on this claim.")).toBeDefined();
});

it("shows an approval and its payment", async () => {
  showClaim(approved, steps);
  const panel = await decisionPanel();
  expect(panel.getByText("Approved")).toBeDefined();
  expect(panel.getAllByText("$420.00")).toHaveLength(2);
  expect(panel.getByText(approval.section)).toBeDefined();
  expect(panel.getByText(approval.reason)).toBeDefined();
  expect(panel.getByText(/^Paid/).textContent).toBe("Paid $420.00");
});

it("shows an approval that hasn't been paid yet", async () => {
  showClaim({ ...approved, payment: null });
  const panel = await decisionPanel();
  expect(panel.getByText("Not paid yet")).toBeDefined();
});

it("shows a decline without a payout", async () => {
  showClaim({
    ...approved,
    decision: { ...approval, decision: "decline", payout: 0 },
    payment: null,
  });
  const panel = await decisionPanel();
  expect(panel.getByText("Declined")).toBeDefined();
  expect(panel.queryByText("$0.00")).toBeNull();
  expect(panel.queryByText(/paid/i)).toBeNull();
});

it("shows each kind of step, with results folded", async () => {
  showClaim(approved, steps);
  expect(
    await screen.findByText('get_claim(claim_id="CLM-1002")'),
  ).toBeDefined();
  const result = screen.getAllByText(/^get_claim: /)[0].closest("details");
  expect(result?.open).toBe(false);
  expect(result?.querySelector("summary")?.textContent).toMatch(/\.\.\.$/);
  expect(result?.querySelector("pre")?.textContent).toBe(steps[1].content);
  const read = screen
    .getByText("Claims manual, section 9: Repeat claims", { exact: false })
    .closest("details");
  expect(read?.open).toBe(false);
  expect(read?.querySelector("summary")?.textContent).toBe(
    "Read Claims manual, section 9: Repeat claims",
  );
  expect(read?.querySelector("pre")?.textContent).toBe(
    "Before deciding any claim.\n\nMost third claims are paid.",
  );
  expect(screen.getByText("Approved and paid.")).toBeDefined();
});

it("shows new steps and the decision as the agent works", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { routes } = showClaim({
    ...claim,
    status: "in_progress",
    thread_id: "t-1",
  });
  expect(await screen.findByText(/No steps yet/)).toBeDefined();

  routes["GET /api/claims/CLM-1002/steps"] = steps.slice(0, 1);
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByText('get_claim(claim_id="CLM-1002")')).toBeDefined();

  routes["GET /api/claims/CLM-1002"] = approved;
  routes["GET /api/claims/CLM-1002/steps"] = steps;
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByText("Approved and paid.")).toBeDefined();
  expect(screen.getAllByText("Decided").length).toBeGreaterThan(0);
});

it("lets a handler sign off a held payment", async () => {
  const { routes, fetchMock } = showClaim(held);
  const panel = await decisionPanel();
  expect(panel.getByText(/waits for a handler's sign-off/)).toBeDefined();
  const button = panel.getByRole("button", { name: "Sign off" });
  expect(button).toHaveProperty("disabled", true);

  const select = panel.getByRole("combobox", { name: "Handler" });
  expect(await within(select).findByText("Dana Whitfield")).toBeDefined();
  expect(within(select).queryByText("Sam Trainee")).toBeNull();

  const signedOff: Claim = {
    ...held,
    status: "decided",
    payment: {
      amount: 1350,
      paid_at: decidedAt,
      signed_off_by: "Dana Whitfield",
    },
  };
  routes["POST /api/claims/CLM-1002/sign-off"] = signedOff;
  fireEvent.change(select, { target: { value: "HND-01" } });
  routes["GET /api/claims/CLM-1002"] = signedOff;
  fireEvent.click(button);

  const payment = await panel.findByText(/signed off by Dana Whitfield/);
  expect(payment.textContent).toBe(
    "Paid $1,350.00, signed off by Dana Whitfield",
  );
  const [, init] = fetchMock.mock.calls.find(
    ([path, request]) =>
      path === "/api/claims/CLM-1002/sign-off" && request?.method === "POST",
  ) ?? [undefined, undefined];
  expect(init?.body).toBe(JSON.stringify({ handler_id: "HND-01" }));
});

it("shows why a sign-off was refused", async () => {
  const { routes } = showClaim(held);
  const panel = await decisionPanel();
  routes["POST /api/claims/CLM-1002/sign-off"] = new Refusal(
    409,
    "Claim CLM-1002 is not waiting for sign-off",
  );
  const select = panel.getByRole("combobox", { name: "Handler" });
  await within(select).findByText("Dana Whitfield");
  fireEvent.change(select, { target: { value: "HND-01" } });
  fireEvent.click(panel.getByRole("button", { name: "Sign off" }));
  expect((await panel.findByRole("alert")).textContent).toBe(
    "Claim CLM-1002 is not waiting for sign-off",
  );
});
