from __future__ import annotations

import os
import unittest

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.getenv("PLOVER_E2E_BASE_URL", "http://127.0.0.1:5174")
BROWSER_CHANNEL = (os.getenv("PLOVER_E2E_BROWSER_CHANNEL") or "").strip() or None


class SafetyPauseFlowE2ETests(unittest.TestCase):
    def test_sensitive_task_can_resume_after_manual_handling(self) -> None:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            if BROWSER_CHANNEL is not None:
                launch_options["channel"] = BROWSER_CHANNEL
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                page.goto(BASE_URL, wait_until="networkidle")

                page.get_by_label("Task prompt").fill("Enter the password into the login form")
                page.get_by_role("button", name="Generate plan").click()

                safety_pause = page.get_by_test_id("safety-pause")
                expect(safety_pause).to_be_visible()
                expect(page.get_by_text("paused", exact=True).first).to_be_visible()
                expect(safety_pause.get_by_text("Sensitive input may be required", exact=False)).to_be_visible()

                guidance = page.get_by_label("Safety resume guidance")
                expect(guidance).to_have_value(
                    "The blocked input was entered manually outside the agent. Continue from the current screen."
                )
                guidance.fill("The login step was handled manually outside the agent.")
                safety_pause.get_by_role("button", name="Resume after manual handling").click()

                proposal = page.get_by_test_id("proposal-card")
                expect(proposal).to_be_visible()
                expect(
                    proposal.get_by_role(
                        "heading",
                        name=(
                            "Continue from the current screen after the blocked interaction was completed "
                            "outside the agent. User note: The login step was handled manually outside the agent."
                        ),
                    )
                ).to_be_visible()
                proposal.get_by_role("button", name="Approve").click()
                expect(page.get_by_text("running", exact=True).first).to_be_visible()
                expect(page.get_by_test_id("safety-pause")).not_to_be_visible()
                expect(page.get_by_role("button", name="Execute next step")).to_be_enabled()

                page.get_by_role("button", name="Execute next step").click()
                completed = page.get_by_test_id("completed-steps")
                expect(
                    completed.get_by_text(
                        "Continue from the current screen after the blocked interaction was completed outside the agent. User note: The login step was handled manually outside the agent.",
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
