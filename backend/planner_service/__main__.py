import os

import uvicorn


if __name__ == "__main__":
    reload_enabled = os.getenv("PLOVER_PLANNER_RELOAD", "").lower() in {"1", "true", "yes", "on"}
    uvicorn.run(
        "planner_service.app:app",
        host=os.getenv("PLOVER_PLANNER_HOST", "127.0.0.1"),
        port=int(os.getenv("PLOVER_PLANNER_PORT", "8000")),
        reload=reload_enabled,
    )
