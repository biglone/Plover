import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from plover_core.models import PlanState, PlanStep, PlanVersion, ReplanCause
from planner_service.database import apply_migrations, connect_sqlite, current_schema_version
from planner_service.store import PostgresPlannerRepository, RunRecord, SqlitePlannerRepository, create_repository


class FakeCursor:
    def __init__(self, row=None, *, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        if self._row is None:
            return []
        if isinstance(self._row, list):
            return self._row
        return [self._row]


class FakePostgresConnection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.schema_migrations: list[tuple[str, str]] = []
        self.closed = False
        self.commits = 0

    def execute(self, query: str, params=None):
        statement = " ".join(query.split())
        if statement.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            return FakeCursor()
        if statement.startswith("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"):
            if not self.schema_migrations:
                return FakeCursor()
            version, applied_at = self.schema_migrations[-1]
            return FakeCursor({"version": version, "applied_at": applied_at})
        if statement.startswith("SELECT version FROM schema_migrations ORDER BY version"):
            return FakeCursor([{"version": version, "applied_at": applied_at} for version, applied_at in self.schema_migrations])
        if statement.startswith("INSERT INTO schema_migrations"):
            self.schema_migrations.append((params[0], params[1]))
            return FakeCursor(rowcount=1)
        if statement.startswith("CREATE TABLE runs"):
            return FakeCursor()
        if statement.startswith("INSERT INTO runs"):
            row = self._row_from_tuple(params)
            self.rows[row["id"]] = row
            return FakeCursor(rowcount=1)
        if statement.startswith("SELECT * FROM runs WHERE id = %s"):
            row = self.rows.get(params[0])
            return FakeCursor(row)
        if statement.startswith("UPDATE runs SET"):
            run_id = params[-1]
            if run_id not in self.rows:
                return FakeCursor(rowcount=0)
            row = self._row_from_tuple((run_id,) + params[:-1])
            self.rows[run_id] = row
            return FakeCursor(rowcount=1)
        raise AssertionError(f"unexpected SQL: {statement}")

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True

    @staticmethod
    def _row_from_tuple(values):
        return {
            "id": values[0],
            "task": values[1],
            "active_version_id": values[2],
            "status": values[3],
            "versions_json": values[4],
            "proposals_json": values[5],
            "events_json": values[6],
            "screenshots_json": values[7],
            "latest_screenshot_png": values[8],
            "live_view_width": values[9],
            "live_view_height": values[10],
        }


def sample_run() -> RunRecord:
    version = PlanVersion(
        id="version-1",
        plan=PlanState(
            completed=(),
            pending=(PlanStep("step-1", "Open the report"),),
        ),
        parent_id=None,
        cause=ReplanCause.INITIAL,
        created_at="now",
    )
    run = RunRecord(
        id="run-1",
        task="Persist this run",
        active_version_id=version.id,
        versions={version.id: version},
        status="running",
    )
    run.set_live_view(b"png", width=320, height=200)
    run.add_screenshot("data:image/png;base64,one")
    run.add_event("plan_created", version_id=version.id)
    return run


class StoreTests(unittest.TestCase):
    def test_sqlite_migrations_are_idempotent_and_track_schema_version(self) -> None:
        with TemporaryDirectory() as directory:
            path = f"{directory}/planner.sqlite3"
            connection = connect_sqlite(path)
            try:
                applied = apply_migrations(connection, "sqlite")
                reapplied = apply_migrations(connection, "sqlite")
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                self.assertEqual(applied, ("0001_runs",))
                self.assertEqual(reapplied, ())
                self.assertIn("runs", tables)
                self.assertIn("schema_migrations", tables)
                self.assertEqual(current_schema_version(connection), "0001_runs")
            finally:
                connection.close()

    def test_postgres_repository_round_trips_run_records(self) -> None:
        connection = FakePostgresConnection()
        repository = PostgresPlannerRepository("postgresql://db.test/plover", connection=connection)

        created = sample_run()
        repository.create(created)
        loaded = repository.get(created.id)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.task, created.task)
        self.assertEqual(loaded.live_view_width, 320)
        self.assertEqual(loaded.events[0]["type"], "plan_created")

        loaded.status = "completed"
        repository.save(loaded)
        updated = repository.get(created.id)
        self.assertEqual(updated.status, "completed")
        self.assertEqual(current_schema_version(connection), "0001_runs")

        repository.close()
        self.assertTrue(connection.closed)
        self.assertGreaterEqual(connection.commits, 3)

    def test_create_repository_supports_sqlite_database_url(self) -> None:
        with TemporaryDirectory() as directory:
            path = f"{directory}/planner.sqlite3"
            with patch.dict(
                "os.environ",
                {
                    "PLOVER_DATABASE_URL": f"sqlite:///{path}",
                    "PLOVER_DATABASE_PATH": "",
                },
                clear=False,
            ):
                repository = create_repository()

            self.assertIsInstance(repository, SqlitePlannerRepository)
            repository.close()

    def test_create_repository_supports_postgres_database_url(self) -> None:
        connection = FakePostgresConnection()
        with patch("planner_service.store.connect_postgres", return_value=connection):
            with patch.dict(
                "os.environ",
                {
                    "PLOVER_DATABASE_URL": "postgresql://db.test/plover",
                    "PLOVER_DATABASE_PATH": "",
                },
                clear=False,
            ):
                repository = create_repository()

        self.assertIsInstance(repository, PostgresPlannerRepository)
        repository.close()
