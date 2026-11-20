import { afterEach, describe, expect, it, vi } from "vitest";
import { api, csrfToken } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "hub_csrf=; Max-Age=0";
});

describe("api", () => {
  it("sends the csrf cookie on mutating calls", async () => {
    document.cookie = "hub_csrf=abc%3D123";
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(csrfToken()).toBe("abc=123");
    await api("/api/jobs/j", { method: "PATCH", body: { title: "Staff" } });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["X-CSRF"]).toBe("abc=123");
    expect(init.body).toBe(JSON.stringify({ title: "Staff" }));
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect((init.headers as Record<string, string>).Accept).toBe("application/json");
  });

  it("sends a resume as raw pdf bytes", async () => {
    const pdf = new Uint8Array([0x25, 0x50, 0x44, 0x46]);
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/candidate/resume", {
      method: "PUT",
      raw: pdf,
      contentType: "application/pdf",
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(pdf);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/pdf");
  });

  it("redirects 401 to the board when next would be root", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    window.history.pushState({}, "", "/");
    await expect(api("/api/whoami")).rejects.toThrow("unauthorized");
    expect(window.location.pathname + window.location.search).toBe("/login?next=/board");
  });
});