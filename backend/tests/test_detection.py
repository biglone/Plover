import unittest
from io import BytesIO

from plover_core.detection import Action, NonProgressDetector, grayscale_dhash, hamming_distance
from plover_core.image import dhash_from_image_bytes


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

    def test_encoded_screenshot_uses_dhash(self) -> None:
        from PIL import Image

        image = Image.new("L", (18, 16), color=0)
        output = BytesIO()
        image.save(output, format="PNG")

        self.assertEqual(dhash_from_image_bytes(output.getvalue()), 0)


if __name__ == "__main__":
    unittest.main()
