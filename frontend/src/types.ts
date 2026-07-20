export type Step = {
  id: string;
  instruction: string;
  status: string;
  ui_summary?: string | null;
  failure_reason?: string | null;
};

export type PlanVersion = {
  id: string;
  parent_id: string | null;
  cause: string;
  created_at: string;
  derived_constraints: string[];
  plan: {
    completed: Step[];
    pending: Step[];
  };
};

export type Proposal = {
  id: string;
  base_version_id: string;
  summary: string;
  rationale: string;
  status: string;
  annotation?: {
    screenshot: string;
    bbox: {
      x: number;
      y: number;
      width: number;
      height: number;
    };
  } | null;
  version: PlanVersion;
};

export type RunState = {
  id: string;
  task: string;
  status: string;
  active_version_id: string;
  active_version: PlanVersion;
  versions: PlanVersion[];
  proposals: Proposal[];
  events: {
    id: string;
    type: string;
    created_at: string;
    [key: string]: unknown;
  }[];
  active_safety_stop: {
    id: string;
    type: string;
    created_at: string;
    category?: string | null;
    reason?: string | null;
    step_id?: string | null;
    [key: string]: unknown;
  } | null;
  screenshot_count: number;
  live_view: {
    image_url: string | null;
    width: number;
    height: number;
  };
};

export type Box = {
  x: number;
  y: number;
  width: number;
  height: number;
};
