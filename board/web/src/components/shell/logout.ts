function readCsrf(): string {
  const hit = document.cookie.split("; ").find((part) => part.startsWith("hub_csrf="));
  if (!hit) return "";
  const raw = hit.slice("hub_csrf=".length);
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

export async function logout(): Promise<void> {
  const token = readCsrf();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["X-CSRF"] = token;
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers,
      credentials: "same-origin",
    });
  } catch {
    // Still leave. A failed POST must not trap the operator on the page.
  }
  window.location.href = "/login";
}
