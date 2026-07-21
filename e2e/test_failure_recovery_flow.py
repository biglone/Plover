from __future__ import annotations

import os
import unittest

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.getenv("PLOVER_E2E_BASE_URL", "http://127.0.0.1:5174")
BROWSER_CHANNEL = (os.getenv("PLOVER_E2E_BROWSER_CHANNEL") or "").strip() or None


class FailureRecoveryFlowE2ETests(unittest.TestCase):
    def test_executor_failure_can_be_recovered_from_the_browser(self) -> None:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            if BROWSER_CHANNEL is not None:
                launch_options["channel"] = BROWSER_CHANNEL
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                page.goto(BASE_URL, wait_until="networkidle")

                page.get_by_label("Task prompt").fill("Recover from the first failed action")
                page.get_by_role("button", name="Generate plan").click()
                page.get_by_role("button", name="Execute next step").click()

                pending = page.get_by_test_id("pending-steps")
                expect(pending.get_by_text("REPEAT_CLICK_MENU", exact=True)).to_be_visible()

                proposal = page.get_by_test_id("proposal-card")
                expect(proposal).to_be_visible()
                expect(proposal.get_by_text("Change tactic and retry the failed action", exact=True)).to_be_visible()
                proposal.get_by_role("button", name="Approve").click()

                timeline = page.get_by_test_id("run-timeline")
                expect(timeline.get_by_text("system driven ir", exact=True)).to_be_visible()
                expect(page.get_by_text("approved", exact=True).first).to_be_visible()

                page.get_by_role("button", name="Execute next step").click()
                completed = page.get_by_test_id("completed-steps")
                expect(
                    completed.get_by_text(
                        "Change tactic and retry the failed action using the current screen",
                        exact=True,
                    )
                ).to_be_visible()

                page.get_by_role("button", name="Execute next step").click()
                expect(completed.get_by_text("Verify the visible outcome and stop", exact=True)).to_be_visible()
                expect(page.get_by_text("completed", exact=True).first).to_be_visible()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
