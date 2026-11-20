import { nextPath } from "./next-path";

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)hub_csrf=([^;]*)/);
  if (!match) {
    return "";
  }
  return decodeURIComponent(match[1]);
}

export async function api<T>(
  path: string,
  opts?: { method?: string; body?: unknown },
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = csrfToken();
  if (token) {
    headers["X-CSRF"] = token;
  }
  if (opts?.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const init: RequestInit = {
    method: opts?.method,
    credentials: "same-origin",
    headers,
  };
  if (opts?.body !== undefined) {
    init.body = JSON.stringify(opts.body);
  }

  const res = await fetch(path, init);

  if (res.status === 401) {
    const loginUrl = `/login?next=${nextPath(window.location.pathname)}`;
    if (import.meta.env.VITEST) {
      window.history.replaceState({}, "", loginUrl);
    }
    window.location.href = loginUrl;
    throw new Error("unauthorized");
  }

  if (!res.ok) {
    let detail: unknown;
    try {
      const json = await res.json();
      detail = json?.detail ?? json;
    } catch {
      detail = await res.text();
    }
    const message =
      typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(message);
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}