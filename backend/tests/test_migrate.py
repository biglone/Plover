import io
import unittest
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch

from planner_service.migrate import main


class MigrateTests(unittest.TestCase):
    def test_main_requires_database_configuration(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "PLOVER_DATABASE_URL": "",
                "PLOVER_DATABASE_PATH": "",
            },
            clear=False,
        ):
            with self.assertRaises(SystemExit) as error:
                main()

        self.assertEqual(
            str(error.exception),
            "Set PLOVER_DATABASE_URL or PLOVER_DATABASE_PATH before running migrations",
        )

    def test_main_applies_and_reuses_sqlite_migrations(self) -> None:
        with TemporaryDirectory() as directory:
            path = f"{directory}/planner.sqlite3"
            with patch.dict(
                "os.environ",
                {
                    "PLOVER_DATABASE_URL": "",
                    "PLOVER_DATABASE_PATH": path,
                },
                clear=False,
            ):
                first_output = io.StringIO()
                with redirect_stdout(first_output):
                    exit_code = main()

                second_output = io.StringIO()
                with redirect_stdout(second_output):
                    second_exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(second_exit_code, 0)
        self.assertIn("Applied migrations to sqlite database", first_output.getvalue())
        self.assertIn("0001_runs", first_output.getvalue())
        self.assertIn("already up to date (0001_runs)", second_output.getvalue())
