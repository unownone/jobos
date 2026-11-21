function csrf() {
  const match = document.cookie.match(/(?:^|; )hub_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export async function api(path, options = {}) {
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
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && data.detail ? data.detail : data && data.message ? data.message : res.statusText;
    const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    error.status = res.status;
    error.data = data;
    throw error;
  }
  return data;
}
