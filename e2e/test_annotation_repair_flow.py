from __future__ import annotations

import os
import re
import unittest

from playwright.sync_api import expect, sync_playwright


BASE_URL = os.getenv("PLOVER_E2E_BASE_URL", "http://127.0.0.1:5174")
BROWSER_CHANNEL = (os.getenv("PLOVER_E2E_BROWSER_CHANNEL") or "").strip() or None


class AnnotationRepairFlowE2ETests(unittest.TestCase):
    def test_annotation_repair_can_be_approved_and_executed(self) -> None:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            if BROWSER_CHANNEL is not None:
                launch_options["channel"] = BROWSER_CHANNEL
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                page.goto(BASE_URL, wait_until="networkidle")

                page.get_by_label("Task prompt").fill("Fill the form")
                page.get_by_role("button", name="Generate plan").click()

                page.get_by_role("button", name="Execute next step").click()
                completed = page.get_by_test_id("completed-steps")
                expect(completed.get_by_text("Capture the current screen before acting", exact=True)).to_be_visible()

                page.get_by_role("button", name="Annotate screenshot").click()
                canvas = page.get_by_test_id("annotation-canvas")
                box = canvas.bounding_box()
                self.assertIsNotNone(box)
                assert box is not None

                page.get_by_test_id("annotation-canvas").evaluate(
                    """(node, coordinates) => {
                        const dispatch = (type, x, y, buttons) => node.dispatchEvent(new PointerEvent(type, {
                            bubbles: true,
                            clientX: x,
                            clientY: y,
                            pointerId: 1,
                            pointerType: "mouse",
                            buttons
                        }));
                        dispatch("pointerdown", coordinates.startX, coordinates.startY, 1);
                        dispatch("pointermove", coordinates.endX, coordinates.endY, 1);
                        dispatch("pointerup", coordinates.endX, coordinates.endY, 0);
                    }""",
                    {
                        "startX": box["x"] + 160,
                        "startY": box["y"] + 120,
                        "endX": box["x"] + 320,
                        "endY": box["y"] + 260,
                    },
                )

                submit = page.get_by_role("button", name="Submit annotation repair")
                expect(submit).to_be_enabled()
                page.get_by_role("button", name="Submit annotation repair").click()

                proposal = page.get_by_test_id("proposal-card")
                expect(proposal).to_be_visible()
                expect(proposal.get_by_role("heading", name="Use the marked screen region to repair the pending action")).to_be_visible()
                expect(proposal.get_by_text(re.compile(r"Click at \d+, \d+"))).to_be_visible()
                proposal.get_by_role("button", name="Approve").click()

                page.get_by_role("button", name="Execute next step").click()
                expect(completed.get_by_text(re.compile(r"Act on the interface region marked at \("))).to_be_visible()
                expect(completed.get_by_text(re.compile(r"Click at \d+, \d+"))).to_be_visible()

                page.get_by_role("button", name="Execute next step").click()
                expect(completed.get_by_text("Verify the visible outcome and stop", exact=True)).to_be_visible()
                expect(page.get_by_text("completed", exact=True).first).to_be_visible()
                expect(page.get_by_test_id("run-timeline").get_by_text("annotation", exact=True).first).to_be_visible()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
