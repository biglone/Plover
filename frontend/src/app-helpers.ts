import type { RunState, StepAction } from "./types";

type RunEvent = RunState["events"][number];

export function formatCause(cause: string): string {
  return cause.split("_").join(" ");
}

export function formatEventType(type: string): string {
  return type.split("_").join(" ");
}

export function shortId(value: string): string {
  if (value.length <= 14) {
    return value;
  }
  return `${value.slice(0, 10)}...${value.slice(-4)}`;
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export function resumePrompt(stop: RunState["active_safety_stop"]): string {
  if (!stop) {
    return "";
  }
  if (stop.category === "sensitive_data") {
    return "The blocked input was entered manually outside the agent. Continue from the current screen.";
  }
  return "The user clarified the intended target. Continue from the current screen.";
}

export function describeEvent(event: RunEvent): string {
  if (typeof event.ui_summary === "string" && event.ui_summary) {
    return event.ui_summary;
  }
  if (event.type === "step_execution_started" && typeof event.instruction === "string") {
    return `Working on: ${event.instruction}`;
  }
  if (event.type === "step_execution_failed" && typeof event.failure_type === "string") {
    return `Execution paused after detecting ${event.failure_type}.`;
  }
  if (event.type === "step_completed") {
    return "Marked the current step complete.";
  }
  if (event.type === "proposal_created") {
    return "Waiting for proposal approval before continuing.";
  }
  if (event.type === "safety_resume_proposed") {
    return "Prepared a localized continuation proposal from the safety pause.";
  }
  if (event.type === "system_recovery_proposed" && typeof event.failure_type === "string") {
    return `Prepared a recovery proposal after detecting ${event.failure_type}.`;
  }
  if (event.type === "safety_stop" && typeof event.reason === "string" && event.reason) {
    return event.reason;
  }
  if (event.type === "execution_blocked" && typeof event.reason === "string" && event.reason) {
    return event.reason;
  }
  if (event.type === "status_changed" && typeof event.status === "string") {
    if (event.status === "failed") {
      return typeof event.reason === "string" && event.reason
        ? `Run marked as failed: ${event.reason}`
        : "Run marked as failed.";
    }
    if (event.status === "paused") {
      return typeof event.reason === "string" && event.reason ? `Run paused: ${event.reason}` : "Run paused.";
    }
    if (event.status === "running") {
      return typeof event.reason === "string" && event.reason
        ? `Run resumed: ${event.reason}`
        : "Run resumed.";
    }
  }
  return formatEventType(event.type);
}

export function eventDetails(event: RunEvent): string[] {
  const details: string[] = [];
  const fields = ["step_id", "proposal_id", "failure_type", "category", "status", "version_id", "reason", "executor_kind", "detail"];
  for (const field of fields) {
    const value = event[field];
    if (typeof value === "string" && value) {
      details.push(`${field.split("_").join(" ")}: ${value}`);
    }
  }
  return details;
}

export function formatStepAction(action: StepAction): string {
  switch (action.kind) {
    case "click":
      return `Click at ${action.x}, ${action.y}`;
    case "double_click":
      return `Double-click at ${action.x}, ${action.y}`;
    case "move":
      return `Move to ${action.x}, ${action.y}`;
    case "drag":
      return `Drag ${action.x}, ${action.y} -> ${action.end_x}, ${action.end_y}`;
    case "type":
      return `Type "${action.text ?? ""}"`;
    case "keys":
      return `Press ${(action.keys ?? []).join(" + ")}`;
    case "scroll":
      return `Scroll ${action.delta}`;
    case "wait":
      return `Wait ${action.milliseconds} ms`;
    case "observe":
      return "Observe screen";
    default:
      return action.kind.split("_").join(" ");
  }
}
