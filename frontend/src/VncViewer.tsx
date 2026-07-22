import { FormEvent, useEffect, useRef, useState } from "react";
import RFB from "@novnc/novnc";
import { websocketUrl } from "./config";

export type VncConnectionState =
  | "connecting"
  | "connected"
  | "credentials"
  | "disconnected";

type VncViewerProps = {
  runId: string;
  onConnectionChange: (state: VncConnectionState) => void;
};

export default function VncViewer({ runId, onConnectionChange }: VncViewerProps) {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<RFB | null>(null);
  const [connectionState, setConnectionState] = useState<VncConnectionState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [credentialTypes, setCredentialTypes] = useState<string[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [viewOnly, setViewOnly] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  function updateState(state: VncConnectionState) {
    setConnectionState(state);
    onConnectionChange(state);
  }

  useEffect(() => {
    const target = targetRef.current;
    if (!target) {
      return;
    }

    updateState("connecting");
    setError(null);
    setCredentialTypes([]);

    const rfb = new RFB(target, websocketUrl("vnc", runId), { shared: true });
    rfbRef.current = rfb;
    rfb.background = "#16231f";
    rfb.scaleViewport = true;
    rfb.resizeSession = false;
    rfb.viewOnly = viewOnly;

    const connectionTimer = window.setTimeout(() => {
      setError("The VNC session did not respond. Check PLOVER_VNC_TARGET and retry.");
      updateState("disconnected");
      rfb.disconnect();
    }, 6000);

    const handleConnect: EventListener = () => {
      window.clearTimeout(connectionTimer);
      updateState("connected");
      rfb.focus();
    };
    const handleDisconnect: EventListener = (event) => {
      window.clearTimeout(connectionTimer);
      const clean = (event as CustomEvent<{ clean?: boolean }>).detail?.clean;
      updateState("disconnected");
      if (!clean) {
        setError("The VNC session could not be reached. Check PLOVER_VNC_TARGET and retry.");
      }
    };
    const handleCredentialsRequired: EventListener = (event) => {
      window.clearTimeout(connectionTimer);
      const types = (event as CustomEvent<{ types?: string[] }>).detail?.types ?? ["password"];
      setCredentialTypes(types);
      updateState("credentials");
    };
    const handleSecurityFailure: EventListener = (event) => {
      const reason = (event as CustomEvent<{ reason?: string }>).detail?.reason;
      setError(reason ? `VNC authentication failed: ${reason}` : "VNC authentication failed.");
    };

    rfb.addEventListener("connect", handleConnect);
    rfb.addEventListener("disconnect", handleDisconnect);
    rfb.addEventListener("credentialsrequired", handleCredentialsRequired);
    rfb.addEventListener("securityfailure", handleSecurityFailure);

    return () => {
      window.clearTimeout(connectionTimer);
      rfb.removeEventListener("connect", handleConnect);
      rfb.removeEventListener("disconnect", handleDisconnect);
      rfb.removeEventListener("credentialsrequired", handleCredentialsRequired);
      rfb.removeEventListener("securityfailure", handleSecurityFailure);
      rfb.disconnect();
      rfbRef.current = null;
      target.replaceChildren();
    };
  }, [retryToken, runId]);

  useEffect(() => {
    if (rfbRef.current) {
      rfbRef.current.viewOnly = viewOnly;
    }
  }, [viewOnly]);

  function submitCredentials(event: FormEvent) {
    event.preventDefault();
    rfbRef.current?.sendCredentials({ username, password });
    setPassword("");
    updateState("connecting");
  }

  return (
    <div className="overflow-hidden rounded-[28px] border border-moss/10 bg-[#16231f]">
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-[#20342d] px-4 py-2 text-white">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-white/70">
          <span
            className={`h-2.5 w-2.5 rounded-full ${connectionState === "connected" ? "bg-[#9fc7a8]" : "bg-wheat"}`}
          />
          {connectionState}
        </div>
        <div className="flex items-center gap-3 text-xs">
          <label className="flex cursor-pointer items-center gap-2 text-white/75">
            <input
              checked={viewOnly}
              className="accent-[#ca6f47]"
              onChange={(event) => setViewOnly(event.target.checked)}
              type="checkbox"
            />
            View only
          </label>
          <button
            className="rounded-full border border-white/15 px-3 py-1.5 font-semibold text-white transition hover:bg-white/10 disabled:opacity-40"
            disabled={connectionState !== "connected" || viewOnly}
            onClick={() => rfbRef.current?.sendCtrlAltDel()}
            type="button"
          >
            Send Ctrl Alt Del
          </button>
        </div>
      </div>

      <div className="relative aspect-[4/3] min-h-[300px]">
        <div ref={targetRef} className="vnc-screen absolute inset-0" tabIndex={0} />

        {connectionState === "connecting" ? (
          <div className="absolute inset-0 grid place-items-center bg-[#16231f]/88 text-center text-white">
            <div>
              <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-wheat" />
              <p className="mt-4 text-sm font-semibold">Connecting to remote desktop</p>
            </div>
          </div>
        ) : null}

        {connectionState === "credentials" ? (
          <div className="absolute inset-0 grid place-items-center bg-[#16231f]/92 p-5">
            <form className="w-full max-w-sm rounded-[24px] border border-white/15 bg-[#20342d] p-5 text-white shadow-xl" onSubmit={submitCredentials}>
              <p className="font-display text-xl">VNC credentials required</p>
              <p className="mt-2 text-sm leading-6 text-white/60">Credentials stay in this browser session.</p>
              {credentialTypes.includes("username") ? (
                <input
                  autoComplete="username"
                  className="mt-4 w-full rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-sm outline-none focus:border-wheat"
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Username"
                  value={username}
                />
              ) : null}
              <input
                autoComplete="current-password"
                autoFocus
                className="mt-3 w-full rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-sm outline-none focus:border-wheat"
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Password"
                type="password"
                value={password}
              />
              <button className="mt-4 w-full rounded-full bg-clay px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#b95f36]" type="submit">
                Connect
              </button>
            </form>
          </div>
        ) : null}

        {connectionState === "disconnected" ? (
          <div className="absolute inset-0 grid place-items-center bg-[#16231f]/92 p-6 text-center text-white">
            <div className="max-w-md">
              <p className="font-display text-xl">Remote desktop disconnected</p>
              <p className="mt-2 text-sm leading-6 text-white/60">{error ?? "The VNC session has ended."}</p>
              <p className="mt-2 text-sm leading-6 text-white/50">
                Switch to <span className="font-semibold text-white/80">Annotate screenshot</span> to review
                executor screenshots when no VNC target is configured.
              </p>
              <button
                className="mt-4 rounded-full bg-clay px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#b95f36]"
                onClick={() => setRetryToken((value) => value + 1)}
                type="button"
              >
                Reconnect
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
