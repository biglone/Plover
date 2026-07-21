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

You can still run checks manually:

```bash
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend run build
```

The initial implementation uses a deterministic mock planner and executor by
default. This keeps the product runnable without credentials while preserving
the integration seam for a vision-capable model and a real VNC environment.

Executor drivers are selected with `PLOVER_EXECUTOR_DRIVER=mock|linux|windows|macos`.
macOS uses `pyautogui` and requires Accessibility and Screen Recording
permissions for the terminal or Executor process.

Planner and Executor entry points now accept local bind settings through
`PLOVER_PLANNER_HOST`, `PLOVER_PLANNER_PORT`, `PLOVER_EXECUTOR_BIND`, and
`PLOVER_EXECUTOR_PORT`. The Vite proxy reads `PLOVER_PLANNER_ORIGIN` when you
need the frontend to point at a non-default Planner address.

Set `PLOVER_DATABASE_PATH=./data/plover.sqlite3` to persist Planner runs,
proposals, screenshots, and timeline events across service restarts.

Set `PLOVER_LLM_ENDPOINT` to use the XML-validated vision-model planner.
`PLOVER_LLM_MODEL` selects the chat-completions model, `PLOVER_LLM_API_KEY`
provides the secret when needed, `PLOVER_LLM_API_KEY_HEADER` and
`PLOVER_LLM_API_KEY_PREFIX` customize how that secret is sent, and
`PLOVER_LLM_EXTRA_HEADERS` accepts a JSON object of provider-specific headers.
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
