import unittest

from executor_service.driver import MockEnvironmentDriver
from executor_service.drivers import MacOSDriver, WindowsDriver, XdotoolDriver, driver_class_for


class DriverFactoryTests(unittest.TestCase):
    def test_factory_exposes_all_supported_platforms(self) -> None:
        self.assertIs(driver_class_for("linux"), XdotoolDriver)
        self.assertIs(driver_class_for("windows"), WindowsDriver)
        self.assertIs(driver_class_for("macos"), MacOSDriver)
        self.assertIs(driver_class_for("mock"), MockEnvironmentDriver)

    def test_factory_rejects_unknown_platform(self) -> None:
        with self.assertRaises(ValueError):
            driver_class_for("plan9")


if __name__ == "__main__":
    unittest.main()
