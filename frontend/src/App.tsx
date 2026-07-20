import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  approveProposal,
  createRun,
  executeNext,
  getRun,
  manualEditPending,
  refreshLiveView,
  resumeRun,
  replanWithAnnotation,
  replanWithGuidance
} from "./api";
import type { Box, Proposal, RunState, Step } from "./types";
import VncViewer, { type VncConnectionState } from "./VncViewer";

const initialPrompt =
  "Transfer the visible values into the report form, verify the result, and stop if a password is required.";

type RunEvent = RunState["events"][number];

function formatCause(cause: string): string {
  return cause.split("_").join(" ");
}

function formatEventType(type: string): string {
  return type.split("_").join(" ");
}

function resumePrompt(stop: RunState["active_safety_stop"]): string {
  if (!stop) {
    return "";
  }
  if (stop.category === "sensitive_data") {
    return "The blocked input was entered manually outside the agent. Continue from the current screen.";
  }
  return "The user clarified the intended target. Continue from the current screen.";
}

function describeEvent(event: RunEvent): string {
  if (typeof event.ui_summary === "string" && event.ui_summary) {
    return event.ui_summary;
  }
  if (event.type === "step_execution_started" && typeof event.instruction === "string") {
    return `Working on: ${event.instruction}`;
  }
  if (event.type === "step_execution_failed" && typeof event.failure_type === "string") {
    return `Execution paused after detecting ${event.failure_type}.`;
  }
  if (event.type === "proposal_created") {
    return "Waiting for proposal approval before continuing.";
  }
  if (event.type === "safety_resume_proposed") {
    return "Prepared a localized continuation proposal from the safety pause.";
  }
  if (event.type === "safety_stop" && typeof event.reason === "string" && event.reason) {
    return event.reason;
  }
  if (event.type === "execution_blocked" && typeof event.reason === "string" && event.reason) {
    return event.reason;
  }
  return formatEventType(event.type);
}

function eventDetails(event: RunEvent): string[] {
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
  onChange,
  imageUrl
}: {
  box: Box | null;
  onChange: (next: Box | null) => void;
  imageUrl: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);

  function point(event: React.PointerEvent<HTMLDivElement>) {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return { x: 0, y: 0 };
    }
    return {
      x: Math.min(Math.max(((event.clientX - rect.left) / rect.width) * 1024, 0), 1024),
      y: Math.min(Math.max(((event.clientY - rect.top) / rect.height) * 768, 0), 768)
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
      {imageUrl ? (
        <img
          alt="Live view"
          className="absolute inset-0 h-full w-full object-cover"
          src={imageUrl}
        />
      ) : (
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(202,111,71,0.18),_transparent_42%),linear-gradient(130deg,_rgba(53,86,74,0.08),_transparent_56%)]" />
      )}
      <div className="absolute inset-0 bg-gradient-to-b from-white/10 via-transparent to-black/5" />
      <div className="absolute left-3 top-3 rounded-full border border-white/70 bg-white/75 px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-moss shadow-sm sm:left-6 sm:top-6 sm:text-xs sm:tracking-[0.2em]">
        Live View 1024 x 768
      </div>
      <div className="absolute inset-x-3 bottom-3 rounded-xl border border-white/60 bg-white/80 p-3 shadow-lg backdrop-blur sm:inset-x-10 sm:bottom-10 sm:rounded-[26px] sm:p-5">
        <p className="font-display text-sm text-ink sm:text-xl">Draw a box to anchor repair in pixel space</p>
        <p className="mt-2 hidden max-w-xl text-sm leading-6 text-ink/65 sm:block">
          The annotation is sent to the planner as a bounding box so only pending steps are revised.
        </p>
      </div>
      {box ? (
        <div
          className="absolute border-[3px] border-clay bg-clay/10"
          style={{
            left: `${(box.x / 1024) * 100}%`,
            top: `${(box.y / 768) * 100}%`,
            width: `${(box.width / 1024) * 100}%`,
            height: `${(box.height / 768) * 100}%`
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
  const [manualEditText, setManualEditText] = useState("");
  const [run, setRun] = useState<RunState | null>(null);
  const [selectedBox, setSelectedBox] = useState<Box | null>(null);
  const [pendingProposalId, setPendingProposalId] = useState<string | null>(null);
  const [liveImageUrl, setLiveImageUrl] = useState<string | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);
  const [liveMode, setLiveMode] = useState<"remote" | "annotate">("remote");
  const [resumeNote, setResumeNote] = useState("");
  const [showLogs, setShowLogs] = useState(false);
  const [vncState, setVncState] = useState<VncConnectionState>("disconnected");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeProposal = useMemo(
    () => run?.proposals.find((proposal) => proposal.status === "pending") ?? null,
    [run]
  );
  const manualEditSteps = useMemo(
    () => manualEditText.split("\n").map((line) => line.trim()).filter(Boolean),
    [manualEditText]
  );

  const currentSummary = useMemo(() => {
    if (!run) {
      return "Create a run to start the execution stream.";
    }
    if (activeProposal) {
      return "Waiting for proposal approval before execution can continue.";
    }
    if (run.active_safety_stop?.reason) {
      return run.active_safety_stop.reason;
    }
    const latest = [...run.events].reverse().find((event) => event.type !== "live_view_refreshed");
    if (latest) {
      return describeEvent(latest);
    }
    return "The plan is ready for its first action.";
  }, [activeProposal, run]);

  useEffect(() => {
    if (!run) {
      setLiveImageUrl(null);
      setLiveConnected(false);
      setLiveMode("remote");
      setManualEditText("");
      setResumeNote("");
      setShowLogs(false);
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

  useEffect(() => {
    if (!run) {
      return;
    }
    setLiveImageUrl(run.live_view.image_url);
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/runs/${run.id}/live`);
    socket.onopen = () => setLiveConnected(true);
    socket.onmessage = (event) => {
      try {
        const frame = JSON.parse(event.data) as {
          type?: string;
          image_url?: string | null;
        };
        if (frame.type === "frame") {
          setLiveImageUrl(frame.image_url ?? null);
        }
      } catch (socketError) {
        console.error(socketError);
      }
    };
    socket.onerror = () => setLiveConnected(false);
    socket.onclose = () => setLiveConnected(false);
    return () => {
      socket.close();
      setLiveConnected(false);
    };
  }, [run?.id]);

  useEffect(() => {
    setResumeNote(run?.active_safety_stop ? resumePrompt(run.active_safety_stop) : "");
  }, [run?.active_safety_stop?.id]);

  useEffect(() => {
    if (!run) {
      return;
    }
    setManualEditText(run.active_version.plan.pending.map((step) => step.instruction).join("\n"));
  }, [run?.active_version_id]);

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
    const screenshot = liveImageUrl ?? run.live_view.image_url;
    if (!screenshot) {
      setError("A live screenshot is required before submitting an annotation.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const proposal = await replanWithAnnotation(run.id, selectedBox, screenshot);
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

  async function handleManualEdit() {
    if (!run || manualEditSteps.length === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const proposal = await manualEditPending(run.id, manualEditSteps);
      setPendingProposalId(proposal.id);
      setRun(await getRun(run.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to create manual patch");
    } finally {
      setBusy(false);
    }
  }

  async function handleResume(handledOutside: boolean) {
    if (!run) {
      return;
    }
    if (!handledOutside && !resumeNote.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const proposal = await resumeRun(run.id, resumeNote.trim(), handledOutside);
      setPendingProposalId(proposal.id);
      setRun(await getRun(run.id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Failed to resume run");
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
                <div className="flex gap-2">
                  <button
                    className="rounded-full border border-moss/15 bg-white px-4 py-2 text-sm font-semibold text-moss transition hover:bg-mist disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={!run || busy}
                    onClick={async () => {
                      if (!run) return;
                      setBusy(true);
                      setError(null);
                      try {
                        setRun(await refreshLiveView(run.id));
                      } catch (requestError) {
                        setError(requestError instanceof Error ? requestError.message : "Failed to refresh live view");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Refresh live view
                  </button>
                  <button
                    className="rounded-full border border-moss/15 bg-moss px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#26453b] disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={!run || busy}
                    onClick={async () => {
                      if (!run) return;
                      setBusy(true);
                      setError(null);
                      try {
                        setRun(await executeNext(run.id));
                      } catch (requestError) {
                        setError(requestError instanceof Error ? requestError.message : "Failed to execute next step");
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Execute next step
                  </button>
                </div>
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
                <div className="flex items-center gap-2">
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${
                      liveMode === "remote"
                        ? vncState === "connected"
                          ? "bg-moss"
                          : "bg-clay"
                        : liveConnected
                          ? "bg-moss"
                          : "bg-ink/25"
                    }`}
                  />
                  <span className="rounded-full bg-mist px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-moss">
                    {liveMode === "remote" ? vncState : liveConnected ? "streaming" : "offline"}
                  </span>
                </div>
              </div>
              <div className="mb-4 flex rounded-full border border-moss/10 bg-canvas p-1" role="group">
                <button
                  className={`flex-1 rounded-full px-4 py-2 text-sm font-semibold transition ${
                    liveMode === "remote" ? "bg-moss text-white shadow-sm" : "text-moss hover:bg-white"
                  }`}
                  onClick={() => setLiveMode("remote")}
                  type="button"
                >
                  Control desktop
                </button>
                <button
                  className={`flex-1 rounded-full px-4 py-2 text-sm font-semibold transition ${
                    liveMode === "annotate" ? "bg-clay text-white shadow-sm" : "text-moss hover:bg-white"
                  }`}
                  onClick={() => setLiveMode("annotate")}
                  type="button"
                >
                  Annotate screenshot
                </button>
              </div>
              <div className="mb-4 rounded-[26px] border border-moss/10 bg-canvas/75 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">
                      Action summary
                    </p>
                    <p className="mt-2 font-display text-lg leading-7 text-ink">{currentSummary}</p>
                  </div>
                  <button
                    className="rounded-full border border-moss/15 bg-white px-4 py-2 text-sm font-semibold text-moss transition hover:bg-mist"
                    onClick={() => setShowLogs((current) => !current)}
                    type="button"
                  >
                    {showLogs ? "Hide detailed logs" : "Show detailed logs"}
                  </button>
                </div>
                {showLogs && run ? (
                  <div className="mt-4 max-h-72 space-y-3 overflow-y-auto pr-1">
                    {[...run.events].reverse().map((event) => (
                      <article
                        key={event.id}
                        className="rounded-2xl border border-moss/10 bg-white/85 px-4 py-3 shadow-sm"
                      >
                        <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                          <div>
                            <p className="text-sm font-semibold capitalize text-moss">
                              {formatEventType(event.type)}
                            </p>
                            <p className="mt-1 text-sm leading-6 text-ink/70">{describeEvent(event)}</p>
                          </div>
                          <p className="text-xs uppercase tracking-[0.16em] text-ink/40">
                            {new Date(event.created_at).toLocaleTimeString()}
                          </p>
                        </div>
                        {eventDetails(event).length ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {eventDetails(event).map((detail) => (
                              <span
                                key={`${event.id}-${detail}`}
                                className="rounded-full bg-canvas px-3 py-1 text-xs text-ink/60"
                              >
                                {detail}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
              {run?.active_safety_stop && !activeProposal ? (
                <div className="mb-4 rounded-[26px] border border-amber-200 bg-amber-50 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">
                    Safety pause
                  </p>
                  <p className="mt-2 text-sm leading-6 text-ink/75">
                    {run.active_safety_stop.reason ?? "The run is waiting for user guidance."}
                  </p>
                  <textarea
                    className="mt-4 min-h-24 w-full rounded-[22px] border border-amber-200 bg-white px-4 py-3 text-sm leading-6 text-ink outline-none transition focus:border-amber-300"
                    value={resumeNote}
                    onChange={(event) => setResumeNote(event.target.value)}
                  />
                  <div className="mt-4 flex flex-col gap-3 md:flex-row">
                    <button
                      className="rounded-full bg-amber-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={busy}
                      onClick={() => handleResume(true)}
                      type="button"
                    >
                      Resume after manual handling
                    </button>
                    <button
                      className="rounded-full border border-amber-200 bg-white px-4 py-3 text-sm font-semibold text-amber-700 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={busy || !resumeNote.trim()}
                      onClick={() => handleResume(false)}
                      type="button"
                    >
                      Clarify and replan
                    </button>
                  </div>
                </div>
              ) : null}
              {liveMode === "remote" ? (
                run ? (
                  <VncViewer runId={run.id} onConnectionChange={setVncState} />
                ) : (
                  <div className="grid aspect-[4/3] min-h-[300px] place-items-center rounded-[28px] border border-moss/10 bg-[#16231f] p-6 text-center text-white">
                    <div>
                      <p className="font-display text-xl">Remote desktop is ready to connect</p>
                      <p className="mt-2 text-sm text-white/60">Create a run to open its VNC session.</p>
                    </div>
                  </div>
                )
              ) : (
                <>
                  <AnnotationLayer
                    box={selectedBox}
                    onChange={setSelectedBox}
                    imageUrl={liveImageUrl ?? run?.live_view.image_url ?? null}
                  />
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
                </>
              )}
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
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-clay">Manual pending edit</p>
                  <h2 className="mt-2 font-display text-2xl text-ink">Directly rewrite the editable suffix</h2>
                </div>
                <span className="rounded-full bg-mist px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-moss">
                  {manualEditSteps.length} steps
                </span>
              </div>
              <textarea
                className="mt-4 min-h-32 w-full rounded-[24px] border border-moss/10 bg-canvas px-4 py-4 text-sm leading-7 text-ink outline-none transition focus:border-moss/30"
                disabled={!run}
                value={manualEditText}
                onChange={(event) => setManualEditText(event.target.value)}
              />
              <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <p className="text-sm text-ink/62">
                  One instruction per line. Completed history stays locked; approval applies only the rewritten pending suffix.
                </p>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <button
                    className="rounded-full border border-moss/15 bg-white px-4 py-3 text-sm font-semibold text-moss transition hover:bg-mist disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={!run}
                    onClick={() =>
                      setManualEditText(
                        run ? run.active_version.plan.pending.map((step) => step.instruction).join("\n") : ""
                      )
                    }
                    type="button"
                  >
                    Reset to current pending
                  </button>
                  <button
                    className="rounded-full bg-moss px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#28483e] disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={!run || busy || manualEditSteps.length === 0}
                    onClick={handleManualEdit}
                    type="button"
                  >
                    Create manual patch
                  </button>
                </div>
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
