export const apiToken = import.meta.env.VITE_PLOVER_API_TOKEN?.trim() ?? "";

export function authHeader(token: string = apiToken): Record<string, string> {
  if (!token) {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}

export function requestHeaders(includeJson = false): Record<string, string> {
  return includeJson ? { "Content-Type": "application/json", ...authHeader() } : authHeader();
}

export function websocketUrl(path: string, runId: string, token: string = apiToken): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL(`${protocol}//${window.location.host}/api/runs/${runId}/${path}`);
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}
