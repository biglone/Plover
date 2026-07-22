import { afterEach, describe, expect, it, vi } from "vitest";
import {
  describeEvent,
  eventDetails,
  formatCause,
  formatEventType,
  formatStepAction,
  resumePrompt,
  shortId
} from "./app-helpers";
import { authHeader, websocketUrl } from "./config";

describe("app helpers", () => {
  it("formats step actions and run metadata", () => {
    expect(formatCause("system_driven_ir")).toBe("system driven ir");
    expect(formatEventType("proposal_created")).toBe("proposal created");
    expect(shortId("run-1234567890abcdef")).toBe("run-123456...cdef");
    expect(formatStepAction({ kind: "drag", x: 1, y: 2, end_x: 3, end_y: 4 })).toBe("Drag 1, 2 -> 3, 4");
  });

  it("describes events and safety resumes", () => {
    expect(
      describeEvent({
        id: "event-1",
        type: "step_execution_failed",
        created_at: "2026-07-22T00:00:00Z",
        failure_type: "REPEAT_CLICK_MENU"
      })
    ).toBe("Execution paused after detecting REPEAT_CLICK_MENU.");
    expect(
      eventDetails({
        id: "event-2",
        type: "status_changed",
        created_at: "2026-07-22T00:00:00Z",
        status: "failed",
        reason: "manual stop"
      })
    ).toEqual(["status: failed", "reason: manual stop"]);
    expect(
      resumePrompt({
        id: "stop-1",
        type: "safety_stop",
        created_at: "2026-07-22T00:00:00Z",
        category: "sensitive_data",
        reason: "Password prompt"
      })
    ).toContain("outside the agent");
  });
});

describe("config helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds auth headers and websocket URLs with tokens", () => {
    vi.stubGlobal("window", {
      location: {
        protocol: "https:",
        host: "plover.test"
      }
    });

    expect(authHeader("secret")).toEqual({ Authorization: "Bearer secret" });
    expect(websocketUrl("live", "run-1", "secret")).toBe(
      "wss://plover.test/api/runs/run-1/live?token=secret"
    );
  });
});
