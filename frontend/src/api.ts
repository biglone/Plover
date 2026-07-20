import type { Box, Proposal, RunState } from "./types";

const jsonHeaders = {
  "Content-Type": "application/json"
};

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createRun(task: string): Promise<RunState> {
  return parse<RunState>(
    await fetch("/api/runs", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ task })
    })
  );
}

export async function getRun(runId: string): Promise<RunState> {
  return parse<RunState>(await fetch(`/api/runs/${runId}`));
}

export async function replanWithGuidance(runId: string, guidance: string): Promise<Proposal> {
  return parse<Proposal>(
    await fetch(`/api/runs/${runId}/replan`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ guidance })
    })
  );
}

export async function replanWithAnnotation(runId: string, box: Box): Promise<Proposal> {
  return parse<Proposal>(
    await fetch(`/api/runs/${runId}/replan`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        annotation: {
          screenshot: "live-view.png",
          x: Math.round(box.x),
          y: Math.round(box.y),
          width: Math.round(box.width),
          height: Math.round(box.height)
        }
      })
    })
  );
}

export async function approveProposal(runId: string, proposalId: string): Promise<RunState> {
  return parse<RunState>(
    await fetch(`/api/runs/${runId}/proposals/${proposalId}/approve`, {
      method: "POST"
    })
  );
}

export async function completeStep(runId: string): Promise<RunState> {
  return parse<RunState>(
    await fetch(`/api/runs/${runId}/steps/complete`, {
      method: "POST"
    })
  );
}

