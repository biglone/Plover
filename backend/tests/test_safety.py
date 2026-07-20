import unittest

from plover_core.safety import inspect_text


class SafetyTests(unittest.TestCase):
    def test_sensitive_input_requires_guidance(self) -> None:
        decision = inspect_text("Enter the account password into the form")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.category, "sensitive_data")

    def test_subjective_ambiguity_requires_guidance(self) -> None:
        decision = inspect_text("Choose whatever looks best")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.category, "subjective_ambiguity")

    def test_specific_instruction_is_allowed(self) -> None:
        self.assertTrue(inspect_text("Click the second option in the menu").allowed)
