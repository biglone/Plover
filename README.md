# Plover

Plover is a plan-centric GUI automation system. It externalizes plans as
versioned artifacts so users can inspect execution, repair only pending work,
and review system-driven recovery proposals.

## Repository Layout

- `backend/plover_core/`: framework-independent plan state, repair, prompts, and
  non-progress detection.
- `backend/planner_service/`: FastAPI planner API.
- `backend/executor_service/`: executor abstractions and gRPC contract.
- `frontend/`: React + Vite agentic interface.
- `docs/`: requirements and the referenced paper.

## Development

The backend targets Python 3.10+. Create a virtual environment and install
`backend/requirements.txt`, then run:

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
```

The frontend uses Node.js and Vite:

```bash
cd frontend
npm install
npm run build
```

The initial implementation uses a deterministic mock planner and executor by
default. This keeps the product runnable without credentials while preserving
the integration seam for a vision-capable model and a real VNC environment.

Executor drivers are selected with `PLOVER_EXECUTOR_DRIVER=mock|linux|windows|macos`.
macOS uses `pyautogui` and requires Accessibility and Screen Recording
permissions for the terminal or Executor process.

Set `PLOVER_DATABASE_PATH=./data/plover.sqlite3` to persist Planner runs,
proposals, screenshots, and timeline events across service restarts.

Set `PLOVER_LLM_ENDPOINT` to use the XML-validated vision-model planner;
`PLOVER_LLM_MODEL` and `PLOVER_LLM_API_KEY` configure the model and optional
authentication. Without it, the deterministic local planner is used.

Set `PLOVER_VNC_TARGET=host:port` to expose a raw VNC WebSocket bridge at
`/api/runs/{run_id}/vnc`.
