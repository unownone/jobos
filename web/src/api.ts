export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

function csrf(): string {
  const match = document.cookie.match(/(?:^|; )hub_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

type ApiBody = BodyInit | null | undefined;

export type ApiOptions = Omit<RequestInit, "body" | "headers"> & {
  body?: ApiBody;
  headers?: HeadersInit;
};

export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type") && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  const token = csrf();
  if (token && options.method && options.method !== "GET") {
    headers.set("X-CSRF", token);
  }
  const res = await fetch(path, { credentials: "include", ...options, headers });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const record = data && typeof data === "object" ? (data as Record<string, unknown>) : null;
    const detail = record?.detail ?? record?.message ?? res.statusText;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ApiError(message, res.status, data);
  }
  return data as T;
}
