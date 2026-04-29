# Playwright/UAT Smoke Flow (DeerFlow → App Garden)

This directory is the QA holding area for browser smoke flows.

DeerFlow currently does not ship Playwright tooling in `frontend/package.json`.
Keep these flows as documented steps until the test infra is intentionally introduced.

## Preconditions

- Local service is reachable at `BASE_URL` (typically `http://localhost:2026`).
- API gates pass:
  - `GET /health`
  - `GET /api/models`
  - `GET /api/mcp/config`
  - `GET /api/skills`
  - `GET /api/agents`

## Minimal smoke plan

1. **API preflight**
   - Validate each JSON contract and status code.
   - Record latency and response shape.

2. **Workspace nav smoke**
   - Open `/workspace`.
   - Confirm redirect or render to chat entrypoint.

3. **Agents smoke**
   - Open `/workspace/agents`.
   - Verify agent page title/heading and “New Agent” action are visible.
   - Open `/workspace/agents/new`.
   - Verify model list request path is attempted by checking browser network log or UI selector presence.

4. **Agent lifecycle smoke (optional, config-aware)**
   - `POST /api/agents` with generated name
   - `GET /api/agents/{name}`
   - `DELETE /api/agents/{name}`

## Suggested concrete Playwright script skeleton

If Playwright is later added, mirror this structure:

```ts
import { expect, test } from "@playwright/test";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:2026";

test("deerflow basic smoke", async ({ page }) => {
  await page.goto(`${BASE_URL}/workspace`, { waitUntil: "domcontentloaded" });

  const health = await page.request.get(`${BASE_URL}/health`);
  expect([200, 302]).toContain(health.status());

  const models = await page.request.get(`${BASE_URL}/api/models`);
  expect(models.ok()).toBeTruthy();
  const body = await models.json();
  expect(Array.isArray(body.models)).toBeTruthy();

  await page.goto(`${BASE_URL}/workspace/agents`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: /new/i }).first()).toBeVisible();
});
```

## UAT evidence capture

- Save:
  - curl output snapshots for all `/api/*` smoke endpoints.
  - Screenshot of `/workspace` and `/workspace/agents/new`.
  - Deployment logs from gateway and nginx during test run.
- Tag artifacts with environment and mode (`gateway`/`standard`), and App Garden branch/commit.
