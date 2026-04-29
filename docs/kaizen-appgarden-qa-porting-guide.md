# Kaizen → DeerFlow App Garden QA Guide

This document is a non-invasive QA and compatibility pass for porting DeerFlow into Kamiwaza/App Garden, using Kaizen as the baseline comparison.

## 1) Kaizen exposure model (backend API behavior)

Kaizen organizes platform concerns around Kubernetes/Kamiwaza-first APIs:

- Model runtime/deployment data is exposed under:
  - `/api/kamiwaza/deployments`
  - `/api/kamiwaza/active-deployments`
  - `/api/kamiwaza/runtime-defaults`
- MCP discovery is versioned under `/api/v1/mcp`, notably:
  - `/api/v1/mcp/toolshed/available`
  - `/api/v1/mcp/test`
- Tool catalog is partially exposed via `/api/tool`:
  - `/api/tool/templates`
  - `/api/tool/deployments`
- Conversations/conversation-model bridging is `/api/llm/*` for inference proxying.
- Health/readiness includes both:
  - `/api/health`
  - `/api/ready` (503 while still initializing)

Kaizen enforces identity in many of these flows (`require_auth`, forward-auth headers), and many routes are explicitly aware of runtime health/readiness (`/api/health`, `/api/ready`) and agent deployment state.

Key Kaizen references:
- [backend/main.py](file:///Users/matt/code/kz/kamiwaza-extensions-kaizen/apps/kaizenv3/backend/app/main.py)
- [backend/api/v1/kamiwaza.py](file:///Users/matt/code/kz/kamiwaza-extensions-kaizen/apps/kaizenv3/backend/app/api/v1/kamiwaza.py)
- [backend/api/v1/mcp.py](file:///Users/matt/code/kz/kamiwaza-extensions-kaizen/apps/kaizenv3/backend/app/api/v1/mcp.py)
- [backend/api/v1/tools.py](file:///Users/matt/code/kz/kamiwaza-extensions-kaizen/apps/kaizenv3/backend/app/api/v1/tools.py)

## 2) DeerFlow exposure map (what is already present)

DeerFlow already exposes useful platform primitives, but with different ownership and naming:

- Configured model catalog: `/api/models` (plus `/api/models/{name}`)
- MCP runtime config: `/api/mcp/config` (`GET` + `PUT`)
- Skills control: `/api/skills*` and custom skill operations
- Agents API (`/api/agents`): list/get/check/create/update/delete; optional by config.
- Gateway surface and runtime dependencies are assembled in:
  - [backend/app/gateway/app.py](file:///Users/matt/code/exocortex/deer-flow-exocortex/backend/app/gateway/app.py)
  - [backend/app/gateway/routers/models.py](file:///Users/matt/code/exocortex/deer-flow-exocortex/backend/app/gateway/routers/models.py)
  - [backend/app/gateway/routers/mcp.py](file:///Users/matt/code/exocortex/deer-flow-exocortex/backend/app/gateway/routers/mcp.py)
  - [backend/app/gateway/routers/skills.py](file:///Users/matt/code/exocortex/deer-flow-exocortex/backend/app/gateway/routers/skills.py)
  - [backend/app/gateway/routers/agents.py](file:///Users/matt/code/exocortex/deer-flow-exocortex/backend/app/gateway/routers/agents.py)

Observed differences to account for in a Kaizen-like App Garden migration:

1. No `/api/v1` shim layer for Kaizen-style tooling/agent-versioned endpoints.
2. No first-class `/api/v1/mcp/toolshed/available` tool catalog endpoint in the same shape as Kaizen.
3. No dedicated `/api/ready` readiness endpoint (only `/health` on gateway).
4. No built-in model deployment discovery flow equivalent to `/api/kamiwaza/active-deployments`.
5. Auth expectations differ: Kaizen hard-routes identity/forward-auth; DeerFlow currently centers service config + UI auth.

### 2.1 Endpoint parity matrix

| Capability | Kaizen | DeerFlow | Gap |
|---|---|---|---|
| Model list | `/api/kamiwaza/active-deployments` | `/api/models` | Deployment metadata vs config-only catalog |
| Model defaults | `/api/kamiwaza/runtime-defaults` | `DEER_FLOW_*` config files | Runtime defaults are file/env-driven |
| MCP discovery | `/api/v1/mcp/toolshed/available` | `/api/mcp/config` | Different shape; no toolshed discovery path |
| Tool catalog | `/api/tool/templates` | `/api/skills` | Different object model and semantics |
| Tool deployments | `/api/tool/deployments` | n/a | Not currently exposed |
| Conversations inference | `/api/llm` | n/a | No direct proxy route in gateway |
| Health | `/api/health`, `/api/ready` | `/health` only | Missing readiness endpoint |
| Auth assumptions | `require_auth` on many routes | config/UI auth mix | Different auth boundary |

## 3) App Garden manifest expectations for DeerFlow

For App Garden parity testing, validate the following at manifest level:

### 3.1 Service layout
- Keep a dedicated backend service (gateway) and frontend service.
- Frontend should be marked as primary UI entry.
- LangGraph may be optional if gateway mode is used, but then `LANGGRAPH_UPSTREAM`/routing needs explicit handling.
- Service naming and dependencies in manifest should reflect runtime order (frontend depends on gateway).

### 3.2 Health contract
- At minimum, health checks can target DeerFlow gateway `/health`:
  - Current behavior: `/health` returns JSON `{status, service}`.
- If App Garden tooling expects readiness separation, add a wrapper (or wrapper route) for `/api/ready` before cutover.
- In both cases, verify compose-level service dependency behavior:
  - Backend service should reach healthy before frontend enters smoke test.
  - If readiness remains unsupported, gate smoke on `/health` + startup wait windows.

### 3.3 Environment and secrets
- Required values for local/compose parity:
  - `BETTER_AUTH_SECRET`
  - `DEER_FLOW_CONFIG_PATH`
  - `DEER_FLOW_EXTENSIONS_CONFIG_PATH`
  - `DEER_FLOW_HOME`
  - optional `NEXT_PUBLIC_BACKEND_BASE_URL` for direct frontend API bypass.
- For parity testing with App Garden expectations, verify secrets are mounted and injectable the same way as:
  - `postgres-password`-like secrets in Kaizen,
  - service URLs and image references.

### 3.4 Route surface expected by Playwright/UI smoke
- `/`, `/workspace`, `/workspace/chats/new`, `/workspace/agents`, `/workspace/agents/new`
- `/health`
- `/api/models`, `/api/mcp/config`, `/api/skills`, `/api/agents`

### 3.5 Compose/dev alignment
- DeerFlow local runtime is defined in:
  - [docker/docker-compose.yaml](file:///Users/matt/code/exocortex/deer-flow-exocortex/docker/docker-compose.yaml)
  - [docker/nginx/nginx.conf](file:///Users/matt/code/exocortex/deer-flow-exocortex/docker/nginx/nginx.conf)
- Use this as the baseline for port mapping and env forwarding before manifest-level migration.

### 3.6 Manifest-to-repo mapping check

When creating an extension manifest, align with Kaizen reference behavior:

- backend healthcheck should be set to a route that becomes true for operational traffic (`/health` today for DeerFlow).
- frontend should be `primary: true` and depend on backend readiness.
- required manifests variables should include:
  - backend image reference (or pinned local dev image),
  - frontend port exposure,
  - secrets injection for authentication keys,
  - optional Postgres/service dependencies if enabled.
- start with parity checks from local compose then lift into:
  - `appgarden/` manifest artifacts,
  - extension-level compose overrides.

## 4) Local deploy verification (manual + commandable)

Before writing/validating App Garden manifests, verify this sequence locally:

1. Deploy in gateway mode for a minimal backend-facing API surface:
```bash
cd /Users/matt/code/exocortex/deer-flow-exocortex
bash scripts/deploy.sh --gateway
```
2. Confirm services are up and reachable:
```bash
docker compose -p deer-flow -f docker/docker-compose.yaml ps
curl -fsS http://localhost:2026/health
```
3. Validate API contracts used by App Garden integration:
```bash
BASE_URL=http://localhost:2026
curl -fsS "$BASE_URL/api/models" | jq '.models | length, .token_usage'
curl -fsS "$BASE_URL/api/mcp/config" | jq '.mcp_servers'
curl -fsS "$BASE_URL/api/skills" | jq '.skills | length'
curl -fsS "$BASE_URL/api/agents" | jq '.agents | length'
```
4. Verify App Garden-style routing assumptions:
```bash
curl -I -fsS http://localhost:2026/health
curl -I -fsS http://localhost:2026/workspace
curl -I -fsS http://localhost:2026/workspace/agents
```
5. Save output for UAT evidence (JSON bodies + logs), and only proceed to manifest changes if all pass.
6. Optional parity check: ensure `/workspace/agents/new` resolves in browser and model dropdown is populated from `/api/models`.

## 5) Suggested Playwright/UAT smoke approach

Keep this plan implementation-light and compatible with current repo (no dependency changes):

- **Phase A: API smoke gates (required, fast)**
  1. `GET /health` returns healthy.
  2. `GET /api/models` includes at least one model object.
  3. `GET /api/mcp/config` returns JSON with `mcp_servers`.
  4. `GET /api/skills` returns skills array.
  5. `GET /api/agents` returns agents array.
  6. Verify response times for each are within a fixed threshold (e.g. 3s in local).

- **Phase B: Minimal UI smoke (for deployment sanity)**
  - Navigate from `/workspace` redirect behavior.
  - `/workspace/agents` renders list/empty-state and `new` entry action.
  - `/workspace/agents/new` loads and allows entering agent metadata; verify a non-blocking fallback if backend is read-only.
  - If `/api/models` is available, confirm model selector is populated.

- **Phase C: Optional agent create/read smoke (if agents API enabled)**
  - Create a unique agent name, POST `/api/agents`.
  - Poll `GET /api/agents/{name}`.
  - Delete test agent and confirm idempotent failure mode (404 after delete).

Use this path to add a future Playwright run under `frontend/tests/playwright` (not added as active test now to avoid forcing dependency changes).

## 6) QA matrix for porting decisions

- If App Garden expects Kaizen-like tool discovery, map `/api/v1/mcp/toolshed/available` usage to either:
  - new DeerFlow compatibility endpoint, or
  - manifest-level test adaptation that queries `/api/mcp/config` instead.
- If App Garden expects ready-state checks, introduce `/api/ready` compatibility in front of `/health` before release.
- If Kaizen auth assumptions leak into UAT scripts, decouple tests to avoid hard-failing in DeerFlow auth style.
- Keep deployment docs and UAT expectations versioned with date and environment (`gateway` vs `standard` mode) because runtime wiring differs.

## 7) Playwright/UAT evidence package

For each UAT run, capture:
- Timestamped `curl` snapshots for all preflight API endpoints under `tmpnotes/qa-$(date +%Y%m%d-%H%M).log`.
- Browser screenshots:
  - `tmpnotes/qa-home.png`
  - `tmpnotes/qa-agents.png`
  - `tmpnotes/qa-agents-new.png`
- `docker compose` logs from both frontend and backend around the test window.
- A one-line verdict for each phase (pass/warn/fail) with any blocking defect IDs.

Use this evidence format as the acceptance criterion for manifest migration handoff.
