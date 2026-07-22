# Plover

Plover is a plan-centric GUI automation system. It externalizes plans as
versioned artifacts so users can inspect execution, repair only pending work,
review system-driven recovery proposals, and directly rewrite the editable
pending suffix before approval. Multiple proposals can be browsed, approved,
discarded, or superseded without mutating completed history.

## Repository Layout

- `backend/plover_core/`: framework-independent plan state, repair, prompts, and
  non-progress detection.
- `backend/planner_service/`: FastAPI planner API.
- `backend/executor_service/`: executor abstractions and gRPC contract.
- `frontend/`: React + Vite agentic interface.
- `docs/`: requirements and the referenced paper.
- `scripts/`: local environment doctor and launcher helpers.

## Development

The backend targets Python 3.10+. Create a virtual environment and install
`backend/requirements.txt`, then run:

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt httpx
npm --prefix frontend install

./scripts/dev_doctor.sh
./scripts/start_local.sh
```

`start_local.sh` loads `.env` and `.env.local`, starts Planner, Executor, and
the Vite frontend together, and writes logs under `.plover-dev/`. Stop the
whole local stack with `Ctrl-C`.

For containers, run:

```bash
docker compose up --build
```

The compose stack serves the frontend on `http://127.0.0.1:3000` and proxies
Planner and its WebSocket routes through the same origin.
It uses the mock executor by default; to drive a real macOS desktop, keep the
Executor on the host and point Planner at it with `PLOVER_EXECUTOR_TARGET`.
On macOS, you can launch the host Executor plus Dockerized Planner and
frontend with `./scripts/start_macos_host_executor.sh`.
That launcher starts the Executor on the host at `0.0.0.0:50051`, points
Planner at `host.docker.internal:50051`, and then runs
`docker compose -f docker-compose.host-executor.yml up --build`.
Before starting a real host Executor, run `./scripts/run_macos_smoke.sh`.
It captures one frame and checks Accessibility without clicking or typing on
the desktop. If it reports a Screen Recording failure, grant the terminal or
Executor process access in **System Settings -> Privacy & Security -> Screen
Recording**, then run the same command again.
To verify the complete Docker Planner-to-host Executor observation path, run
`./scripts/run_macos_host_executor_smoke.sh` after Docker Desktop is running.
It starts isolated temporary services, creates a run, refreshes its Live View,
and asserts two normalized screenshots. It never calls the execution endpoint,
so it does not click, type, or scroll on the desktop. Temporary containers,
database volume, and host Executor are stopped automatically.

You can still run checks manually:

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
./scripts/check_openapi.sh
npm --prefix frontend run test
./scripts/run_acceptance.sh
npm --prefix frontend run build
./scripts/run_quality_gate.sh
./scripts/run_browser_e2e.sh
./scripts/run_browser_recovery_e2e.sh
./scripts/run_browser_safety_e2e.sh
./scripts/run_browser_annotation_e2e.sh
./scripts/run_macos_smoke.sh
./scripts/run_macos_motion_smoke.sh
./scripts/run_macos_host_executor_smoke.sh
```

The initial implementation uses a deterministic mock planner and executor by
default. This keeps the product runnable without credentials while preserving
the integration seam for a vision-capable model and a real VNC environment.

The browser E2E script starts an isolated local Planner and Vite frontend,
then checks the manual action-manifest path from proposal creation through
approval, execution, and timeline rendering. The launcher prefers a locally
installed Google Chrome or Microsoft Edge when available; otherwise install
Playwright Chromium once before the first run:

```bash
.venv/bin/python -m playwright install chromium
```

`./scripts/run_browser_recovery_e2e.sh` reuses the same launcher but starts
Planner with `PLOVER_LOCAL_EXECUTOR_SCENARIO=fail_once` so the browser can
verify the automatic recovery proposal flow end to end.

`./scripts/run_browser_safety_e2e.sh` covers the safety pause path where a
sensitive task is resumed after the operator handles the blocked interaction
outside the agent.

`./scripts/run_browser_annotation_e2e.sh` covers screenshot-grounded repair:
draw a bounding box, generate an annotation proposal, approve it, and execute
the repaired pending suffix.

`./scripts/run_quality_gate.sh` runs the backend test suite, production
frontend build, and all browser E2E flows serially. The same quality gate runs
on every GitHub pull request and push through `.github/workflows/quality-gate.yml`.

Executor drivers are selected with `PLOVER_EXECUTOR_DRIVER=mock|linux|windows|macos`.
macOS uses `pyautogui` and requires Accessibility and Screen Recording
permissions for the terminal or Executor process.

`./scripts/run_macos_motion_smoke.sh` additionally validates Accessibility by
moving the cursor once to its current coordinate. It never clicks, types, or
scrolls.

Planner and Executor entry points now accept local bind settings through
`PLOVER_PLANNER_HOST`, `PLOVER_PLANNER_PORT`, `PLOVER_EXECUTOR_BIND`, and
`PLOVER_EXECUTOR_PORT`. The Vite proxy reads `PLOVER_PLANNER_ORIGIN` when you
need the frontend to point at a non-default Planner address.
Set `PLOVER_API_TOKEN` to require bearer auth on Planner HTTP and websocket
routes, and mirror the same value in `VITE_PLOVER_API_TOKEN` when building or
running the frontend.

Set `PLOVER_DATABASE_PATH=./data/plover.sqlite3` to persist Planner runs,
proposals, screenshots, and timeline events across service restarts.
Planner applies migrations automatically on startup, and
`./scripts/migrate_database.sh` can be used to initialize or upgrade the
schema ahead of time:

```bash
PLOVER_DATABASE_PATH=./data/plover.sqlite3 \
./scripts/migrate_database.sh
```

The same migration command works for PostgreSQL deployments when
`PLOVER_DATABASE_URL` is set to a `postgresql://` or `postgres://` DSN.

Set `PLOVER_LLM_ENDPOINT` to use the XML-validated vision-model planner.
`PLOVER_LLM_MODEL` selects the chat-completions model, `PLOVER_LLM_API_KEY`
provides the secret when needed, `PLOVER_LLM_API_KEY_HEADER` and
`PLOVER_LLM_API_KEY_PREFIX` customize how that secret is sent, and
`PLOVER_LLM_EXTRA_HEADERS` accepts a JSON object of provider-specific headers.
Planner responses may include optional `<actions>` blocks so executor steps can
carry explicit pointer, keyboard, scroll, wait, and observe primitives.
Set `PLOVER_LLM_STREAM=1` to consume OpenAI-compatible SSE streaming responses.
If the provider requires a session bootstrap or token refresh step, configure
`PLOVER_LLM_BOOTSTRAP_ENDPOINT` plus the optional
`PLOVER_LLM_BOOTSTRAP_METHOD`, `PLOVER_LLM_BOOTSTRAP_HEADERS`,
`PLOVER_LLM_BOOTSTRAP_BODY`, `PLOVER_LLM_BOOTSTRAP_TOKEN_PATH`,
`PLOVER_LLM_BOOTSTRAP_EXPIRES_IN_PATH`,
`PLOVER_LLM_BOOTSTRAP_HEADER_NAME`, and
`PLOVER_LLM_BOOTSTRAP_HEADER_PREFIX` settings.
Bootstrap responses can also set cookies, which Planner persists across later
chat-completion requests automatically.
Without `PLOVER_LLM_ENDPOINT`, the deterministic local planner is used.

Set `PLOVER_VNC_TARGET=host:port` to expose a raw VNC WebSocket bridge at
`/api/runs/{run_id}/vnc`. The React Live View uses noVNC to provide interactive
desktop control, view-only access, credential prompts, and reconnect support.
The screenshot annotation mode remains available when VNC is not configured.
Executor and external observation frames are normalized to `1024 x 768` so
annotation coordinates remain stable across platforms.

Safety-sensitive references such as "stop if a password is required" are
treated as policy instructions rather than secret material. When a run is
paused for a real sensitive or ambiguous interaction, the UI now exposes an
explicit resume flow that can either capture a clarification or continue after
the user completed the blocked action outside the agent.
Operators can also pause a run manually, mark it as failed with a rationale,
and resume only after pending proposals or safety stops have been cleared.
When the current tactic is visibly stuck, the UI can also report an executor
failure type and ask Planner to generate a system-driven recovery proposal.
If the visible state is already correct, operators can manually mark the
current step complete without mutating completed history.
