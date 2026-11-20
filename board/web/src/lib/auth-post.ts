import { csrfToken } from "./api";

// Login and bootstrap return 401 for a bad secret. api() would leave the form for /login.
export function assignHref(href: string): void {
  if (import.meta.env.VITEST) {
    window.history.replaceState({}, "", href);
  }
  window.location.href = href;
}

export async function postJson(path: string, body: unknown): Promise<Response> {
  return fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF": csrfToken(),
    },
    body: JSON.stringify(body),
  });
}

export async function errorText(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.length > 0) return detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        const message = (detail as { message: unknown }).message;
        if (typeof message === "string" && message.length > 0) return message;
      }
      if (detail !== undefined && detail !== null) return JSON.stringify(detail);
    }
  } catch {
    // The body was empty or not JSON.
  }
  return res.statusText || "request failed";
}
