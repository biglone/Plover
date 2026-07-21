from __future__ import annotations

import os
import unittest

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.getenv("PLOVER_E2E_BASE_URL", "http://127.0.0.1:5174")
BROWSER_CHANNEL = (os.getenv("PLOVER_E2E_BROWSER_CHANNEL") or "").strip() or None


class ManualActionFlowE2ETests(unittest.TestCase):
    def test_manual_action_manifest_can_be_approved_and_executed(self) -> None:
        """Exercise the browser path for an explicit action from authoring through execution."""
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            if BROWSER_CHANNEL is not None:
                launch_options["channel"] = BROWSER_CHANNEL
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                page.goto(BASE_URL, wait_until="networkidle")

                page.get_by_label("Task prompt").fill("Open the E2E report")
                page.get_by_role("button", name="Generate plan").click()
                expect(page.get_by_text("Pending", exact=True)).to_be_visible()

                page.get_by_label("Manual pending instructions").fill("Open the E2E report")
                page.get_by_label("Manual action manifest").fill(
                    """[
  [
    { "kind": "click", "x": 320, "y": 240 },
    { "kind": "observe" }
  ]
]"""
                )
                page.get_by_role("button", name="Create manual patch").click()

                proposal = page.get_by_test_id("proposal-card")
                expect(proposal).to_be_visible()
                expect(proposal.get_by_text("Click at 320, 240", exact=True)).to_be_visible()
                proposal.get_by_role("button", name="Approve").click()

                expect(page.get_by_test_id("run-timeline").get_by_text("Proposal branch", exact=True)).to_be_visible()
                expect(page.get_by_text("approved", exact=True).first).to_be_visible()

                page.get_by_role("button", name="Execute next step").click()
                completed = page.get_by_test_id("completed-steps")
                expect(completed.get_by_text("Open the E2E report", exact=True)).to_be_visible()
                expect(completed.get_by_text("Click at 320, 240", exact=True)).to_be_visible()
                expect(page.get_by_text("completed", exact=True).first).to_be_visible()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
