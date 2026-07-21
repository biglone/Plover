# Plover Implementation Notes

This repository contains a runnable first vertical slice of the design in
`需求与技术设计文档.md` and the referenced Plover paper.

## Implemented

- Immutable plan state with `completed` and editable `pending` suffixes.
- Versioned plan revisions with parent links, causes, derived constraints, and
  approval before activation.
- Planner REST API for creating runs, requesting natural-language or annotated
  replans, proposing direct manual edits, approving proposals, and progressing
  steps.
- Screenshot retention capped at the three most recent artifacts per run and
  forwarded as visual context for model-driven repair proposals.
- SQLite persistence for plans, proposals, timeline events, screenshots, and
  the latest Live View frame.
- Safety stops for sensitive data and subjective ambiguity before execution,
  plus an explicit resume endpoint and UI for post-pause recovery.
- Manual operator status controls for pausing a run, marking it failed with a
  rationale, and resuming only after safety stops and pending proposals are
  cleared.
- A manual current-step completion action for operator-approved progress when
  the visible state is already correct.
- WebSocket Live View stream at `/api/runs/{run_id}/live` with 1024 x 768
  screenshot frames consumed directly by the React interface, including
  normalized screenshots from native drivers and external observation feeds.
- External Live View observation sources can replace the default executor
  screenshot feed through `PLOVER_OBSERVATION_PATH` or
  `PLOVER_OBSERVATION_URL`.
- Raw VNC WebSocket bridge at `/api/runs/{run_id}/vnc`, configured with
  `PLOVER_VNC_TARGET=host:port`.
- Browser noVNC client with interactive control, view-only mode, in-memory
  credential prompts, reconnection, and screenshot annotation fallback.
- Executor gRPC contract for pointer, keyboard, scroll, wait, and observation
  primitives.
- Conservative system-driven non-progress detection using repeated canonical
  actions and screenshot dHash stability.
- Executor failures create a versioned plan state with the current step marked
  failed, then keep the run paused until a repair proposal replaces that step.
- Ubuntu `xdotool`, Windows `pyautogui`, and macOS `pyautogui` driver adapters
  behind the same executor protocol.
- React + Tailwind UI for plan inspection, live-view annotation, proposal
  queue browsing, discard/approve actions, direct pending-step editing,
  manual operator controls, failure-report-driven recovery proposals,
  progressive-disclosure logs, and Git-style version provenance.
- Executor action traces surfaced in the run log so the UI can expose both
  high-level summaries and detailed primitive-level events.

## Run Locally

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt httpx
npm --prefix frontend install

./scripts/dev_doctor.sh
./scripts/start_local.sh
```

The launcher reads `.env` and `.env.local`, starts Planner, Executor, and the
frontend together, and writes service logs to `.plover-dev/`. Press `Ctrl-C`
to stop the local stack.

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

You can still run the checks manually:

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
./scripts/run_acceptance.sh
npm --prefix frontend run build
```

The default planner and executor are deterministic local implementations so
the workflow runs without credentials or a VNC server. The Live View offers
an interactive VNC desktop when `PLOVER_VNC_TARGET` is configured and retains
an annotation-capable screenshot mode as a fallback. To run Planner against a
separate Executor process, set `PLOVER_EXECUTOR_TARGET`, for example:

```bash
PLOVER_EXECUTOR_TARGET=127.0.0.1:50051 \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

To point Live View at an external screenshot feed instead of the executor's
own frame capture, set `PLOVER_OBSERVATION_PATH` or `PLOVER_OBSERVATION_URL`.
Path and header templates may include `{run_id}`.

Planner uses in-memory state by default. Set `PLOVER_DATABASE_PATH` to persist
run artifacts across restarts:

```bash
PLOVER_DATABASE_PATH=./data/plover.sqlite3 \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

The service applies schema migrations automatically on startup. To initialize
or upgrade the database explicitly before launching Planner, run:

```bash
PLOVER_DATABASE_PATH=./data/plover.sqlite3 \
./scripts/migrate_database.sh
```

For multi-process deployments, set `PLOVER_DATABASE_URL` to a SQLite or
PostgreSQL DSN:

```bash
PLOVER_DATABASE_URL=postgresql://plover:secret@db.example.com/plover \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

The same script also supports DSN-based deployments:

```bash
PLOVER_DATABASE_URL=postgresql://plover:secret@db.example.com/plover \
./scripts/migrate_database.sh
```

Set `PLOVER_LLM_ENDPOINT` to switch Planner to the OpenAI-compatible vision
model adapter. `PLOVER_LLM_MODEL` defaults to `computer-use`,
`PLOVER_LLM_API_KEY` is optional for local endpoints, and header-based auth can
be customized with `PLOVER_LLM_API_KEY_HEADER`,
`PLOVER_LLM_API_KEY_PREFIX`, and `PLOVER_LLM_EXTRA_HEADERS`. Set
`PLOVER_LLM_STREAM=1` to consume SSE chat-completions responses. For providers
that need a bootstrap or refresh call before chat completions, configure
`PLOVER_LLM_BOOTSTRAP_ENDPOINT` and its companion settings for method, headers,
body, token path, expiry path, and injected header naming. Any cookies set by
that bootstrap response are persisted and replayed on subsequent bootstrap and
chat-completion requests:

```bash
PLOVER_LLM_ENDPOINT=http://127.0.0.1:9000/v1/chat/completions \
PLOVER_LLM_MODEL=computer-use \
PLOVER_LLM_API_KEY=replace-me \
PLOVER_LLM_API_KEY_HEADER=Authorization \
PLOVER_LLM_API_KEY_PREFIX='Bearer ' \
PLOVER_LLM_EXTRA_HEADERS='{"x-deployment":"staging"}' \
PLOVER_LLM_STREAM=1 \
PLOVER_LLM_BOOTSTRAP_ENDPOINT=http://127.0.0.1:9000/session \
PLOVER_LLM_BOOTSTRAP_METHOD=POST \
PLOVER_LLM_BOOTSTRAP_HEADERS='{"x-bootstrap":"true"}' \
PLOVER_LLM_BOOTSTRAP_BODY='{"grant_type":"client_credentials"}' \
PLOVER_LLM_BOOTSTRAP_TOKEN_PATH='session.access_token' \
PLOVER_LLM_BOOTSTRAP_EXPIRES_IN_PATH='session.expires_in' \
PLOVER_LLM_BOOTSTRAP_HEADER_NAME=Authorization \
PLOVER_LLM_BOOTSTRAP_HEADER_PREFIX='Bearer ' \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

For providers that need multiple bootstrap hops, set
`PLOVER_LLM_BOOTSTRAP_FLOW` to a JSON array of request steps. Each step can
capture JSON fields into later `${var}` placeholders, and cookies still persist
across the whole flow.

Model responses must contain the `<analysis>` and `<steps>` XML blocks. Invalid
XML or a response that changes completed history is rejected and recorded
without executing any action.

The Executor driver is selected independently:

```bash
PLOVER_EXECUTOR_DRIVER=macos \
PYTHONPATH=backend .venv/bin/python -m executor_service
```

Planner and Executor bind settings can be overridden with
`PLOVER_PLANNER_HOST`, `PLOVER_PLANNER_PORT`, `PLOVER_EXECUTOR_BIND`, and
`PLOVER_EXECUTOR_PORT`. The local Vite proxy reads `PLOVER_PLANNER_ORIGIN` if
the frontend should target a non-default Planner address.

On macOS, grant the terminal or packaged Executor process access under
**System Settings -> Privacy & Security -> Accessibility** and **Screen
Recording**. Without both permissions, mouse/keyboard actions or screenshots
may fail even though the gRPC service is healthy.

To connect the browser directly to a VNC session, start Planner with a target
that speaks the RFB protocol. The browser connects to Planner's same-origin
WebSocket endpoint, so no separate websockify process is required:

```bash
PLOVER_VNC_TARGET=127.0.0.1:5900 \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

The browser prompts for credentials only when the VNC server requests them.
Credentials remain in component memory and are not sent to Planner storage.

When Planner pauses for a real safety stop, the frontend exposes two recovery
paths:

- Resume after the user handled the blocked interaction outside the agent.
- Submit a clarification that produces a localized pending-suffix proposal.
