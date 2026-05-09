# Office Orchestrator

The central management service for The Agentic Office. This service:

- Routes requests between offices
- Manages inter-office communication
- Performs C-suite routing with confidence scoring
- Applies fallback escalation when primary office dispatch fails
- Supports role-based workflows for selected domains (creator/reviewer/approver)
- Persists transactions to PostgreSQL
- Exposes dispatch monitoring and capability metadata

## API Endpoints

- `GET /health` - Health check
- `GET /offices` - List all office statuses
- `POST /request` - Submit a cross-office request (authenticated + rate limited)
- `POST /message` - Route natural-language task to office manager (authenticated + rate limited)
- `GET /dispatch-log` - Query dispatch transactions with filters (authenticated + rate limited)
- `GET /stats` - Operational metrics and rate-limit configuration (authenticated + rate limited)
- `GET /metrics` - Prometheus-style telemetry export (authenticated + rate limited)
- `GET /capabilities` - Office capability map
- `GET /logs` - View transaction logs (authenticated + rate limited)
- `GET /approvals/pending` - View queued requests waiting for final user approval (authenticated + rate limited)
- `POST /approvals/{request_id}/approve` - Approve or reject queued requests (authenticated + rate limited)

## Authentication

Sensitive dispatch endpoints require header:

- `X-API-Key: <ORCHESTRATOR_API_KEY>`

The service requires `ORCHESTRATOR_API_KEY` to be set at startup.

## Rate Limiting

Configured per API key in a sliding window:

- `ORCHESTRATOR_MESSAGE_RATE_LIMIT` (default `60`)
- `ORCHESTRATOR_DISPATCH_RATE_LIMIT` (default `120`)
- `ORCHESTRATOR_REQUEST_RATE_LIMIT` (default `120`)
- `ORCHESTRATOR_RATE_WINDOW_SECONDS` (default `60`)

## CORS

Configure allowed origins explicitly (comma-separated):

- `ORCHESTRATOR_CORS_ALLOWED_ORIGINS` (default `http://localhost:8000,http://127.0.0.1:8000`)
- `ORCHESTRATOR_CORS_ALLOW_CREDENTIALS` (default `true`)

## Security Profiles

Security behavior is profile-driven using `ENVIRONMENT`:

- Dev/Test (`dev`, `development`, `test`):
	- Metadata endpoints (`/offices`, `/capabilities`) are open by default.
	- Default local CORS origins are applied if none are specified.

- Non-dev (`staging`, `prod`, `production`, or any other value):
	- Metadata endpoints require API key auth and rate limiting by default.
	- `ORCHESTRATOR_CORS_ALLOWED_ORIGINS` must be explicitly set.
	- `ORCHESTRATOR_API_KEY` must not be the dev key and must be at least 16 chars.

Optional override:

- `ORCHESTRATOR_REQUIRE_METADATA_AUTH` (`true`/`false`) to force metadata endpoint auth policy.

## Persistence

Transactions are stored in PostgreSQL via `DATABASE_URL`.

## Role-Based Workflow Logic

`POST /message` now supports policy-driven multi-role workflows.

Current first-class policies:

- `social-media` requests follow:
	- Creator: Social Media Manager Agent
	- Reviewer: HR Manager Agent
	- Approver: Office Orchestrator (C-suite quality gate)

- `procurement` requests follow:
	- Creator: Procurement Manager Agent
	- Reviewer: Finance Manager Agent
	- Approver: Office Orchestrator (C-suite quality gate)

- `hr` hiring requests (hire/recruit/candidate/headcount/interview/job keywords) follow:
	- Creator: HR Manager Agent
	- Reviewer: Finance Manager Agent
	- Approver: Office Orchestrator (C-suite quality gate)

Workflow details are returned in the message response under `response.workflow` and each stage is captured in `attempts`.

For these governed workflows, the orchestrator now returns status `needs_final_approval` after internal checks pass.

This is the explicit final queue step before execution is considered finalized:

1. Office workflow runs creator -> reviewer -> executive approver.
2. Request enters `needs_final_approval` queue.
3. User calls `POST /approvals/{request_id}/approve` to approve or reject.
4. Final status transitions to `completed` (approved) or `failed` (rejected).

## Running

```bash
python -m uvicorn main:app --reload
```

Port: 8000

## Testing

Run the orchestrator test suite:

```bash
pytest tests -v
```

Default non-Docker workflow for every change:

```bash
pytest tests/test_local_process_smoke.py -v
pytest tests -v
```

Run only live HTTP endpoint tests (launches a real uvicorn process):

```bash
pytest tests/test_http_endpoints_live.py -v
```

Run local process smoke tests (no Docker; orchestrator + finance office subprocesses):

```bash
pytest tests/test_local_process_smoke.py -v
```

Run release-gate test set (required before merge):

```bash
powershell -ExecutionPolicy Bypass -File ../../scripts/run-release-gate.ps1
```

Run docker-compose smoke integration tests (postgres + orchestrator + finance office):

```bash
RUN_DOCKER_SMOKE=1 pytest tests/test_docker_compose_smoke.py -v
```

## Office URL Overrides

For non-Docker local runs, override office service URLs with environment variables:

- `OFFICE_URL_SALES`
- `OFFICE_URL_HR`
- `OFFICE_URL_CUSTOMER_SERVICE`
- `OFFICE_URL_PROCUREMENT`
- `OFFICE_URL_FINANCE`
- `OFFICE_URL_MANUFACTURING`
- `OFFICE_URL_SOCIAL_MEDIA`

## Local One-Command Startup

Launch orchestrator + one office service locally:

```bash
powershell -ExecutionPolicy Bypass -File ../../scripts/run-local-office-stack.ps1 -Office finance -OllamaModel mistral
```

This sets all `OFFICE_URL_*` variables to the selected local office URL so auto-routed requests do not fail DNS resolution in single-office local sessions.

It also enables the strict local LLM profile:

- `LLM_STRICT_LOCAL=true`
- `LLM_PRIMARY_PROVIDER=ollama`
- `LLM_ENABLE_FALLBACK=false`
- `OLLAMA_URL` and `OLLAMA_MODEL` from script args/defaults

In strict local mode, office startup fails fast if Ollama is unreachable or if the configured model is missing.

## Local LLM Integration Test (Environment Gated)

Run this test regularly on local machines with Ollama available:

```bash
RUN_LOCAL_LLM_INTEGRATION=1 OLLAMA_MODEL=mistral pytest tests/test_local_llm_integration.py -v
```

The test verifies:

- Finance office reports `llm_status.primary == "ollama"`
- Strict local mode is active
- Message dispatch response text is non-empty

## CI/CD

- `.github/workflows/ci.yml` runs non-Docker tests and release-gate tests on push/PR.
- `.github/workflows/nightly-docker-smoke.yml` runs Docker smoke tests on a nightly schedule and manual trigger (optional, non-blocking).
