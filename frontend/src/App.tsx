import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  approveProposal,
  completeStep,
  createRun,
  getRun,
  replanWithAnnotation,
  replanWithGuidance
} from "./api";
import type { Box, Proposal, RunState, Step } from "./types";

const initialPrompt =
  "Transfer the visible values into the report form, verify the result, and stop if a password is required.";

function formatCause(cause: string): string {
  return cause.split("_").join(" ");
}

function StepList({ steps, title }: { steps: Step[]; title: string }) {
  return (
    <section className="rounded-[28px] border border-moss/15 bg-white/70 p-5 shadow-panel">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-display text-lg text-ink">{title}</h3>
        <span className="rounded-full bg-mist px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-moss">
          {steps.length} steps
        </span>
      </div>
      <div className="space-y-3">
        {steps.length === 0 ? (
          <p className="text-sm text-ink/55">No steps in this section.</p>
        ) : null}
        {steps.map((step, index) => (
          <article
            key={step.id}
            className="rounded-2xl border border-moss/10 bg-canvas/80 p-4 transition hover:-translate-y-0.5"
          >
            <div className="mb-2 flex items-start justify-between gap-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">
                  {index + 1 < 10 ? `0${index + 1}` : index + 1}
                </div>
                <p className="mt-1 text-sm leading-6 text-ink">{step.instruction}</p>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-medium capitalize text-moss shadow-sm">
                {step.status}
              </span>
            </div>
            {step.ui_summary ? <p className="text-xs text-ink/60">{step.ui_summary}</p> : null}
            {step.failure_reason ? <p className="mt-2 text-xs text-clay">{step.failure_reason}</p> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function AnnotationLayer({
  box,
  onChange
}: {
  box: Box | null;
  onChange: (next: Box | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);

  function point(event: React.PointerEvent<HTMLDivElement>) {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return { x: 0, y: 0 };
    }
    return {
      x: Math.min(Math.max(event.clientX - rect.left, 0), rect.width),
      y: Math.min(Math.max(event.clientY - rect.top, 0), rect.height)
    };
  }

  return (
    <div
      ref={containerRef}
      className="annotation-grid relative aspect-[4/3] overflow-hidden rounded-[28px] border border-moss/10 bg-[#fffdf8]"
      onPointerDown={(event) => {
        startRef.current = point(event);
        onChange({ x: startRef.current.x, y: startRef.current.y, width: 0, height: 0 });
      }}
      onPointerMove={(event) => {
        if (!startRef.current) {
          return;
        }
        const current = point(event);
        const x = Math.min(startRef.current.x, current.x);
        const y = Math.min(startRef.current.y, current.y);
        const width = Math.abs(startRef.current.x - current.x);
        const height = Math.abs(startRef.current.y - current.y);
        onChange({ x, y, width, height });
      }}
      onPointerUp={() => {
        startRef.current = null;
      }}
      onPointerLeave={() => {
        startRef.current = null;
      }}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(202,111,71,0.18),_transparent_42%),linear-gradient(130deg,_rgba(53,86,74,0.08),_transparent_56%)]" />
      <div className="absolute left-6 top-6 rounded-full border border-white/70 bg-white/75 px-3 py-1 text-xs uppercase tracking-[0.2em] text-moss shadow-sm">
        Live View 1024 x 768
      </div>
      <div className="absolute inset-x-10 bottom-10 rounded-[26px] border border-white/60 bg-white/72 p-5 shadow-lg backdrop-blur">
        <p className="font-display text-xl text-ink">Draw a box to anchor repair in pixel space</p>
        <p className="mt-2 max-w-xl text-sm leading-6 text-ink/65">
          This mock live view stands in for the VNC feed. The annotation is sent to the planner as
          a bounding box so only pending steps are revised.
        </p>
      </div>
      {box ? (
        <div
          className="absolute border-[3px] border-clay bg-clay/10"
          style={{
            left: box.x,
            top: box.y,
            width: box.width,
            height: box.height
          }}
        >
          <div className="absolute -top-8 left-0 rounded-full bg-clay px-3 py-1 text-xs font-semibold text-white">
            {Math.round(box.x)}, {Math.round(box.y)} / {Math.round(box.width)} x {Math.round(box.height)}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ProposalCard({
  proposal,
  onApprove
}: {
  proposal: Proposal;
  onApprove: (proposal: Proposal) => void;
}) {
  return (
    <section className="rounded-[28px] border border-clay/25 bg-[#fff8f3] p-5 shadow-panel">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">Proposal</p>
          <h3 className="mt-2 font-display text-lg text-ink">{proposal.summary}</h3>
          <p className="mt-2 text-sm leading-6 text-ink/70">{proposal.rationale}</p>
        </div>
        <button
          className="rounded-full bg-clay px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#b95f36]"
          onClick={() => onApprove(proposal)}
        >
          Approve
        </button>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-clay/15 bg-white/75 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-moss">Derived constraints</p>
          <ul className="mt-3 space-y-2 text-sm text-ink/75">
            {proposal.version.derived_constraints.map((constraint) => (
              <li key={constraint}>{constraint}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-2xl border border-clay/15 bg-white/75 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-moss">Pending patch</p>
          <div className="mt-3 space-y-2 text-sm text-ink/75">
            {proposal.version.plan.pending.map((step) => (
              <div key={step.id} className="rounded-xl bg-canvas px-3 py-2">
                {step.instruction}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function App() {
  const [task, setTask] = useState(initialPrompt);
  const [guidance, setGuidance] = useState("Choose the visible recovery option instead.");
  const [run, setRun] = useState<RunState | null>(null);
  const [selectedBox, setSelectedBox] = useState<Box | null>(null);
  const [pendingProposalId, setPendingProposalId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeProposal = useMemo(
    () => run?.proposals.find((proposal) => proposal.status === "pending") ?? null,
    [run]
  );

  useEffect(() => {
    if (!run) {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const next = await getRun(run.id);
        setRun(next);
      } catch (pollError) {
        console.error(pollError);
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [run?.id]);

  async function handleCreateRun(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setRun(await createRun(task));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to create run");
    } finally {
      setBusy(false);
    }
  }

  async function handleGuidanceReplan() {
    if (!run || !guidance.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const proposal = await replanWithGuidance(run.id, guidance.trim());
      setPendingProposalId(proposal.id);
      setRun(await getRun(run.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to replan");
    } finally {
      setBusy(false);
    }
  }

  async function handleAnnotationReplan() {
    if (!run || !selectedBox || selectedBox.width < 4 || selectedBox.height < 4) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const proposal = await replanWithAnnotation(run.id, selectedBox);
      setPendingProposalId(proposal.id);
      setRun(await getRun(run.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to submit annotation");
    } finally {
      setBusy(false);
    }
  }

  async function handleApprove(proposal: Proposal) {
    if (!run) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setRun(await approveProposal(run.id, proposal.id));
      setPendingProposalId(null);
      setSelectedBox(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to approve proposal");
    } finally {
      setBusy(false);
    }
  }

  async function handleCompleteStep() {
    if (!run) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setRun(await completeStep(run.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to complete step");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-canvas px-4 py-6 font-body text-ink md:px-8">
      <div className="mx-auto max-w-[1480px]">
        <section className="mb-6 overflow-hidden rounded-[34px] bg-[linear-gradient(135deg,#35564a_0%,#28483e_52%,#ca6f47_100%)] px-6 py-7 text-white shadow-panel md:px-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-wheat">
                Plan-Centric GUI Automation
              </p>
              <h1 className="mt-3 font-display text-4xl leading-tight md:text-5xl">
                Plover turns hidden agent planning into a shared workspace.
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-white/78 md:text-base">
                Review the task plan, submit natural-language or screenshot-grounded repairs, and
                approve only localized updates while completed history stays immutable.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-3xl border border-white/15 bg-white/10 px-4 py-4 backdrop-blur">
                <p className="text-xs uppercase tracking-[0.2em] text-white/60">Run status</p>
                <p className="mt-2 font-display text-2xl capitalize">{run?.status ?? "idle"}</p>
              </div>
              <div className="rounded-3xl border border-white/15 bg-white/10 px-4 py-4 backdrop-blur">
                <p className="text-xs uppercase tracking-[0.2em] text-white/60">Versions</p>
                <p className="mt-2 font-display text-2xl">{run?.versions.length ?? 0}</p>
              </div>
              <div className="rounded-3xl border border-white/15 bg-white/10 px-4 py-4 backdrop-blur">
                <p className="text-xs uppercase tracking-[0.2em] text-white/60">Screenshots</p>
                <p className="mt-2 font-display text-2xl">{run?.screenshot_count ?? 0}</p>
              </div>
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[1.12fr_1fr]">
          <section className="space-y-6">
            <section className="rounded-[30px] border border-moss/10 bg-white/72 p-5 shadow-panel md:p-6">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">Planner chat</p>
                  <h2 className="mt-2 font-display text-2xl text-ink">Prompt, inspect, and revise</h2>
                </div>
                <button
                  className="rounded-full border border-moss/15 bg-moss px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#26453b] disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={busy}
                  onClick={handleCompleteStep}
                >
                  Complete next step
                </button>
              </div>
              <form className="space-y-4" onSubmit={handleCreateRun}>
                <textarea
                  className="min-h-36 w-full rounded-[24px] border border-moss/10 bg-canvas px-4 py-4 text-sm leading-7 text-ink outline-none ring-0 transition focus:border-moss/30"
                  value={task}
                  onChange={(event) => setTask(event.target.value)}
                />
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <p className="text-sm text-ink/62">
                    The initial offline planner creates a deterministic draft that can be revised
                    through guidance or annotations.
                  </p>
                  <button
                    className="rounded-full bg-clay px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#b95f36] disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={busy}
                    type="submit"
                  >
                    {run ? "Create new run" : "Generate plan"}
                  </button>
                </div>
              </form>
              {error ? <p className="mt-4 text-sm text-clay">{error}</p> : null}
            </section>

            {run ? (
              <>
                <div className="grid gap-6 lg:grid-cols-2">
                  <StepList steps={run.active_version.plan.completed} title="Completed" />
                  <StepList steps={run.active_version.plan.pending} title="Pending" />
                </div>

                {activeProposal ? (
                  <ProposalCard proposal={activeProposal} onApprove={handleApprove} />
                ) : (
                  <section className="rounded-[28px] border border-moss/10 bg-white/72 p-5 shadow-panel">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-moss">
                      Proposal queue
                    </p>
                    <p className="mt-3 text-sm leading-6 text-ink/65">
                      No pending proposal. Use the guidance box or draw an annotation to trigger a
                      localized replan.
                    </p>
                  </section>
                )}
              </>
            ) : null}
          </section>

          <section className="space-y-6">
            <section className="rounded-[30px] border border-moss/10 bg-white/72 p-5 shadow-panel md:p-6">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">Execution monitor</p>
                  <h2 className="mt-2 font-display text-2xl text-ink">Live view and grounded repair</h2>
                </div>
                <span className="rounded-full bg-mist px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-moss">
                  {run?.active_version.cause ? formatCause(run.active_version.cause) : "no run"}
                </span>
              </div>
              <AnnotationLayer box={selectedBox} onChange={setSelectedBox} />
              <div className="mt-4 flex flex-col gap-3 md:flex-row">
                <button
                  className="rounded-full bg-moss px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#28483e] disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!run || busy || !selectedBox || selectedBox.width < 4 || selectedBox.height < 4}
                  onClick={handleAnnotationReplan}
                >
                  Submit annotation repair
                </button>
                <button
                  className="rounded-full border border-moss/15 bg-white px-4 py-3 text-sm font-semibold text-moss transition hover:bg-mist disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!selectedBox}
                  onClick={() => setSelectedBox(null)}
                >
                  Clear box
                </button>
              </div>
            </section>

            <section className="rounded-[30px] border border-moss/10 bg-white/72 p-5 shadow-panel md:p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">Natural-language guidance</p>
              <textarea
                className="mt-4 min-h-28 w-full rounded-[24px] border border-moss/10 bg-canvas px-4 py-4 text-sm leading-7 text-ink outline-none transition focus:border-moss/30"
                value={guidance}
                onChange={(event) => setGuidance(event.target.value)}
              />
              <div className="mt-4 flex items-center justify-between gap-3">
                <p className="text-sm text-ink/62">Replan only the pending suffix while keeping completed steps fixed.</p>
                <button
                  className="rounded-full bg-clay px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#b95f36] disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!run || busy || !guidance.trim()}
                  onClick={handleGuidanceReplan}
                >
                  Request replan
                </button>
              </div>
            </section>

            <section className="rounded-[30px] border border-moss/10 bg-white/72 p-5 shadow-panel md:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">Run timeline</p>
                  <h2 className="mt-2 font-display text-2xl text-ink">Branching provenance</h2>
                </div>
                {pendingProposalId ? (
                  <span className="rounded-full bg-clay/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-clay">
                    Pending {pendingProposalId}
                  </span>
                ) : null}
              </div>
              <div className="mt-6 space-y-4">
                {run?.versions.map((version, index) => (
                  <div key={version.id} className="flex gap-4">
                    <div className="flex w-16 flex-col items-center">
                      <div className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-moss bg-mist font-display text-sm text-moss">
                        {index + 1}
                      </div>
                      {index < run.versions.length - 1 ? <div className="mt-2 h-full w-px bg-moss/20" /> : null}
                    </div>
                    <div className="flex-1 rounded-[24px] border border-moss/10 bg-canvas/75 p-4">
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div>
                          <p className="text-sm font-semibold capitalize text-moss">{formatCause(version.cause)}</p>
                          <p className="text-xs uppercase tracking-[0.2em] text-ink/45">{version.id}</p>
                        </div>
                        <div className="text-xs text-ink/55">
                          {version.plan.completed.length} completed / {version.plan.pending.length} pending
                        </div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {version.derived_constraints.map((constraint) => (
                          <span
                            key={`${version.id}-${constraint}`}
                            className="rounded-full bg-white px-3 py-1 text-xs text-ink/65 shadow-sm"
                          >
                            {constraint}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                )) ?? <p className="text-sm text-ink/60">Create a run to start the timeline.</p>}
              </div>
            </section>
          </section>
        </div>
      </div>
    </main>
  );
}
