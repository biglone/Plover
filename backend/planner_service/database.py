from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import sqlite3
from typing import Any, Literal


DatabaseKind = Literal["sqlite", "postgres"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DatabaseTarget:
    kind: DatabaseKind
    location: str


@dataclass(frozen=True)
class Migration:
    version: str
    sqlite_statements: tuple[str, ...]
    postgres_statements: tuple[str, ...]

    def statements_for(self, kind: DatabaseKind) -> tuple[str, ...]:
        return self.sqlite_statements if kind == "sqlite" else self.postgres_statements


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version="0001_runs",
        sqlite_statements=(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                active_version_id TEXT NOT NULL,
                status TEXT NOT NULL,
                versions_json TEXT NOT NULL,
                proposals_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                screenshots_json TEXT NOT NULL,
                latest_screenshot_png BLOB NOT NULL,
                live_view_width INTEGER NOT NULL,
                live_view_height INTEGER NOT NULL
            )
            """.strip(),
        ),
        postgres_statements=(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                active_version_id TEXT NOT NULL,
                status TEXT NOT NULL,
                versions_json TEXT NOT NULL,
                proposals_json TEXT NOT NULL,
                events_json TEXT NOT NULL,
                screenshots_json TEXT NOT NULL,
                latest_screenshot_png BYTEA NOT NULL,
                live_view_width INTEGER NOT NULL,
                live_view_height INTEGER NOT NULL
            )
            """.strip(),
        ),
    ),
)


def resolve_database_target_from_env() -> DatabaseTarget | None:
    database_url = (os.getenv("PLOVER_DATABASE_URL") or "").strip()
    if database_url:
        if database_url.startswith("sqlite:///"):
            return DatabaseTarget(kind="sqlite", location=database_url.removeprefix("sqlite:///"))
        if database_url.startswith(("postgresql://", "postgres://")):
            return DatabaseTarget(kind="postgres", location=database_url)
        raise RuntimeError("PLOVER_DATABASE_URL must use sqlite:/// or postgresql://")
    database_path = (os.getenv("PLOVER_DATABASE_PATH") or "").strip()
    if database_path:
        return DatabaseTarget(kind="sqlite", location=database_path)
    return None


def connect_sqlite(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def connect_postgres(dsn: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:  # pragma: no cover - exercised in deployment environments
        raise RuntimeError("Install psycopg to use PostgreSQL persistence") from error
    return psycopg.connect(dsn, row_factory=dict_row)


def _ensure_migration_table(connection: Any) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row[key]
    return row[0]


def _applied_versions(connection: Any) -> set[str]:
    return {
        _row_value(row, "version")
        for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    }


def apply_migrations(connection: Any, kind: DatabaseKind) -> tuple[str, ...]:
    _ensure_migration_table(connection)
    applied = _applied_versions(connection)
    new_versions: list[str] = []
    placeholder = "?" if kind == "sqlite" else "%s"
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        for statement in migration.statements_for(kind):
            connection.execute(statement)
        connection.execute(
            f"INSERT INTO schema_migrations (version, applied_at) VALUES ({placeholder}, {placeholder})",
            (migration.version, _utc_now()),
        )
        new_versions.append(migration.version)
    connection.commit()
    return tuple(new_versions)


def current_schema_version(connection: Any) -> str | None:
    row = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return _row_value(row, "version")
