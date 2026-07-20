import unittest

from plover_core.detection import Action, NonProgressDetector, grayscale_dhash, hamming_distance


class DetectionTests(unittest.TestCase):
    def test_dhash_and_hamming_distance(self) -> None:
        pixels = [[column for column in range(9)] for _ in range(8)]
        digest = grayscale_dhash(pixels)

        self.assertEqual(digest, 0)
        self.assertEqual(hamming_distance(0b1010, 0b0011), 2)

    def test_repeated_static_actions_trigger_detection(self) -> None:
        detector = NonProgressDetector()

        result = None
        for _ in range(3):
            result = detector.observe(Action("click", "menu"), screenshot_hash=1234)

        self.assertIsNotNone(result)
        self.assertEqual(result.failure_type, "REPEAT_CLICK_MENU")
        self.assertEqual(result.screenshot_distances, (0, 0))

    def test_visual_change_prevents_detection(self) -> None:
        detector = NonProgressDetector()

        for digest in (1, 1, 1):
            detector.observe(Action("click", "menu"), screenshot_hash=digest)
        result = detector.observe(Action("click", "menu"), screenshot_hash=1 << 50)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

