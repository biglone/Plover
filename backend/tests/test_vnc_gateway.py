import unittest

from planner_service.vnc_gateway import VncTarget, VncTargetError


class VncGatewayTests(unittest.TestCase):
    def test_parses_ipv4_and_ipv6_targets(self) -> None:
        self.assertEqual(VncTarget.parse("127.0.0.1:5900"), VncTarget("127.0.0.1", 5900))
        self.assertEqual(VncTarget.parse("[::1]:5901"), VncTarget("::1", 5901))

    def test_rejects_malformed_targets(self) -> None:
        for value in ("", "localhost", "localhost:nope", "localhost:70000"):
            with self.subTest(value=value):
                with self.assertRaises(VncTargetError):
                    VncTarget.parse(value)
