# Plover Implementation Notes

This repository contains a runnable first vertical slice of the design in
`需求与技术设计文档.md` and the referenced Plover paper.

## Implemented

- Immutable plan state with `completed` and editable `pending` suffixes.
- Versioned plan revisions with parent links, causes, derived constraints, and
  approval before activation.
- Planner REST API for creating runs, requesting natural-language or annotated
  replans, approving proposals, and progressing steps.
- Screenshot retention capped at the three most recent artifacts per run.
- SQLite persistence for plans, proposals, timeline events, screenshots, and
  the latest Live View frame.
- Safety stops for sensitive data and subjective ambiguity before execution.
- Executor gRPC contract for pointer, keyboard, scroll, wait, and observation
  primitives.
- Conservative system-driven non-progress detection using repeated canonical
  actions and screenshot dHash stability.
- Ubuntu `xdotool`, Windows `pyautogui`, and macOS `pyautogui` driver adapters
  behind the same executor protocol.
- React + Tailwind UI for plan inspection, live-view annotation, proposal
  approval, and Git-style version provenance.

## Run Locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt httpx
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v

PYTHONPATH=backend .venv/bin/python -m planner_service
cd frontend && npm install && npm run dev
```

The default planner and executor are deterministic local implementations so
the workflow runs without credentials or a VNC server. The UI's live view is
an annotation-capable screenshot surface. To run Planner against a separate
Executor process, set `PLOVER_EXECUTOR_TARGET`, for example:

```bash
PLOVER_EXECUTOR_TARGET=127.0.0.1:50051 \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

Planner uses in-memory state by default. Set `PLOVER_DATABASE_PATH` to persist
run artifacts across restarts:

```bash
PLOVER_DATABASE_PATH=./data/plover.sqlite3 \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

Set `PLOVER_LLM_ENDPOINT` to switch Planner to the OpenAI-compatible vision
model adapter. `PLOVER_LLM_MODEL` defaults to `computer-use`, and
`PLOVER_LLM_API_KEY` is optional for local endpoints:

```bash
PLOVER_LLM_ENDPOINT=http://127.0.0.1:9000/v1/chat/completions \
PLOVER_LLM_MODEL=computer-use \
PLOVER_LLM_API_KEY=replace-me \
PYTHONPATH=backend .venv/bin/python -m planner_service
```

Model responses must contain the `<analysis>` and `<steps>` XML blocks. Invalid
XML or a response that changes completed history is rejected and recorded
without executing any action.

The Executor driver is selected independently:

```bash
PLOVER_EXECUTOR_DRIVER=macos \
PYTHONPATH=backend .venv/bin/python -m executor_service
```

On macOS, grant the terminal or packaged Executor process access under
**System Settings -> Privacy & Security -> Accessibility** and **Screen
Recording**. Without both permissions, mouse/keyboard actions or screenshots
may fail even though the gRPC service is healthy.

## Integration Boundaries

- Add provider-specific authentication and streaming to the
  OpenAI-compatible vision-model adapter if required by the deployment.
- Route executor `failure_type` responses to
  `POST /api/runs/{run_id}/failures` to surface a system-driven IR proposal.
- Provide a VNC gateway that serves 1024 x 768 screenshots to the frontend and
  forwards user annotation metadata.
- Move SQLite to Postgres or another shared database for multi-process
  deployment.
- Add an explicit user-guidance flow to resume a safety-paused run after the
  sensitive or ambiguous input has been supplied outside the agent.
