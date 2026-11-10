import { type APIRequestContext, expect, test } from "@playwright/test";

// These tests stand in for the agent by calling the API through the
// dashboard's proxy, and watch the claim page update without a reload.

async function send(request: APIRequestContext, path: string, data: object) {
  const response = await request.post(path, { data });
  expect(response.ok()).toBe(true);
}

async function writeTodos(request: APIRequestContext, statuses: string[]) {
  const todos = statuses.map((status, index) => ({
    content: `Work CLM-101${String(index)}`,
    status,
  }));
  const response = await request.put("/api/runs/e2e-run/todos", {
    data: { todos },
  });
  expect(response.ok()).toBe(true);
}

test("the claim page shows the agent at work", async ({ page, request }) => {
  await page.goto("/claims/CLM-1003");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting")).toBeVisible();
  await expect(page.getByText(/No steps yet/)).toBeVisible();

  await send(request, "/api/claims/CLM-1003/start", { thread_id: "e2e-1" });
  await send(request, "/api/claims/CLM-1003/steps", {
    kind: "tool_call",
    content: 'get_claim(claim_id="CLM-1003")',
  });
  await send(request, "/api/claims/CLM-1003/steps", {
    kind: "tool_result",
    content: 'get_claim: {"claim_id":"CLM-1003"}',
  });
  await expect(heading.getByText("In progress")).toBeVisible();
  await expect(
    page.getByText("The agent is working on this claim."),
  ).toBeVisible();
  await expect(page.getByText('get_claim(claim_id="CLM-1003")')).toBeVisible();
  await expect(
    page.getByText('get_claim: {"claim_id":"CLM-1003"}').first(),
  ).toBeVisible();

  await send(request, "/api/claims/CLM-1003/decision", {
    decision: "approve",
    payout: 500,
    section: "Section 7, Emergency Medical",
    reason: "The treatment was necessary and covered.",
  });
  await send(request, "/api/claims/CLM-1003/payment", { amount: 500 });
  await send(request, "/api/claims/CLM-1003/steps", {
    kind: "message",
    content: "Approved and paid $500.00.",
  });
  await expect(heading.getByText("Decided")).toBeVisible();
  const decision = page.locator("section", {
    has: page.getByRole("heading", { name: "Decision" }),
  });
  await expect(decision.getByText("Approved")).toBeVisible();
  await expect(decision.getByText("Paid $500.00")).toBeVisible();
  await expect(page.getByText("Approved and paid $500.00.")).toBeVisible();
});

test("a handler signs off a payout over the limit", async ({
  page,
  request,
}) => {
  await send(request, "/api/claims/CLM-1020/start", { thread_id: "e2e-2" });
  await send(request, "/api/claims/CLM-1020/decision", {
    decision: "approve",
    payout: 1350,
    section: "Section 5, Baggage and Personal Effects",
    reason: "The loss is covered.",
  });
  const refused = await request.post("/api/claims/CLM-1020/payment", {
    data: { amount: 1350 },
  });
  expect(refused.status()).toBe(403);

  await page.goto("/claims/CLM-1020");
  await expect(
    page.locator(".claim-heading").getByText("Waiting for sign-off"),
  ).toBeVisible();
  await page.getByRole("combobox", { name: "Handler" }).selectOption({
    label: "Dana Whitfield",
  });
  await page.getByRole("button", { name: "Sign off" }).click();
  await expect(
    page.locator(".claim-heading").getByText("Decided"),
  ).toBeVisible();
  await expect(
    page.getByText("Paid $1,350.00, signed off by Dana Whitfield"),
  ).toBeVisible();
});

// Starting a run fails any claim left in progress, so this test runs after the
// others in this file, which run in order.
test("the queue shows the agent's to-do list as it goes", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const run = page.locator("section", {
    has: page.getByRole("heading", { name: "Current run" }),
  });
  await expect(run.getByText(/No run yet/)).toBeVisible();

  await send(request, "/api/runs", { run_id: "e2e-run", cap: 3 });
  await writeTodos(request, ["to_do", "to_do", "to_do"]);
  const items = run.getByRole("listitem");
  await expect(items).toHaveText([
    /To do\s*Work CLM-1010/,
    /To do\s*Work CLM-1011/,
    /To do\s*Work CLM-1012/,
  ]);

  await writeTodos(request, ["done", "in_progress", "to_do"]);
  await expect(items).toHaveText([
    /Done\s*Work CLM-1010/,
    /In progress\s*Work CLM-1011/,
    /To do\s*Work CLM-1012/,
  ]);
  await expect(run.getByText(/1 of 3 done/)).toBeVisible();

  await send(request, "/api/runs/e2e-run/finish", {
    summary: "Worked 3 claims.",
  });
  await expect(run.getByText("Worked 3 claims.")).toBeVisible();
  await expect(run.getByText(/^Finished at/)).toBeVisible();
});
