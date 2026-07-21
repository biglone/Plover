from __future__ import annotations

from planner_service.database import (
    apply_migrations,
    connect_postgres,
    connect_sqlite,
    current_schema_version,
    resolve_database_target_from_env,
)


def main() -> int:
    target = resolve_database_target_from_env()
    if target is None:
        raise SystemExit("Set PLOVER_DATABASE_URL or PLOVER_DATABASE_PATH before running migrations")

    if target.kind == "sqlite":
        connection = connect_sqlite(target.location)
    else:
        connection = connect_postgres(target.location)
    try:
        applied = apply_migrations(connection, target.kind)
        version = current_schema_version(connection)
    finally:
        connection.close()

    location = target.location if target.kind == "sqlite" else "<postgres>"
    if applied:
        print(f"Applied migrations to {target.kind} database at {location}: {', '.join(applied)}")
    else:
        print(f"Database at {location} is already up to date ({version or 'no migrations'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
