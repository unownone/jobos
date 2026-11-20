import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { pageVariants } from "@/lib/motion";

import { HomePage } from "./HomePage";
import homeSource from "./HomePage.tsx?raw";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const apiMock = vi.mocked(api);

const REQUIRED_IDS = [
  "whoLabel",
  "logoutBtn",
  "connLabel",
  "kpiFoundToday",
  "kpiAppliedToday",
  "kpiOldestDays",
  "kpiOldestSub",
  "funnelLegend",
  "agentWorking",
  "oldestBody",
  "main",
] as const;

const DASHBOARD = {
  funnel: { found: 3, applied: 1, outreached: 0 },
  agents: { total: 2, working: 1, live: 1 },
  today: { found: 2, applied: 1, day_start: "2026-11-20T00:00:00Z" },
  oldest_in_pipeline: {
    id: "j",
    company: "TicketCo",
    title: "Staff",
    status: "discovered",
    location: "",
    pay: "",
    posted_at: "",
    created_at: "",
    days_in_pipeline: 4,
    posted_known: false,
  },
};

const WHO = {
  user: { display_name: "Ada" },
  actor: "ada-actor",
  user_id: "user-1",
  kind: "owner",
  role: "admin",
};

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function byId(id: string): HTMLElement {
  const node = document.getElementById(id);
  if (!(node instanceof HTMLElement)) {
    throw new Error(`missing #${id}`);
  }
  return node;
}

beforeEach(() => {
  window.history.replaceState({}, "", "/home");
  apiMock.mockReset();
  const matchMedia = (query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  });
  vi.stubGlobal("matchMedia", matchMedia);
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HomePage", () => {
  it("shows the harness before data returns, then the dashboard fixture", async () => {
    const whoami = deferred<typeof WHO>();
    const dashboard = deferred<typeof DASHBOARD>();
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") return whoami.promise;
      if (path === "/api/dashboard") return dashboard.promise;
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HomePage />);

    expect(document.querySelector("[data-testid='hub-frame']")).toBeInTheDocument();
    expect(document.querySelector("[data-testid='hub-scroll']")?.className).toContain("overflow-y-auto");
    expect(document.querySelector("h1")).toHaveTextContent("jobOS Harness");
    expect(document.body).toHaveTextContent("helps find jobs");
    expect(document.querySelector("h2")?.parentElement).toBeTruthy();
    const headings = [...document.querySelectorAll("h2")].map((node) => node.textContent);
    expect(headings).toContain("Hunt funnel");
    expect(headings).toContain("Oldest open job");
    for (const id of REQUIRED_IDS) {
      expect(document.getElementById(id)).toBeInTheDocument();
    }
    expect(document.querySelector("header #connLabel")).toBe(byId("connLabel"));
    expect(byId("connLabel")).toHaveTextContent("signing in");
    expect(byId("whoLabel").textContent).toBe("");
    expect(byId("kpiFoundToday")).toHaveTextContent("—");
    expect(byId("kpiAppliedToday")).toHaveTextContent("—");
    expect(byId("kpiOldestDays")).toHaveTextContent("—");
    expect(byId("agentWorking")).toHaveTextContent("—");
    expect(document.querySelector("canvas")).not.toBeInTheDocument();
    expect(apiMock.mock.calls.map((call) => call[0])).toEqual(["/api/whoami"]);

    whoami.resolve(WHO);
    await waitFor(() => {
      expect(byId("whoLabel")).toHaveTextContent("Ada · owner");
    });
    expect(byId("connLabel")).toHaveTextContent("signed in");
    expect(apiMock.mock.calls.map((call) => call[0])).toEqual(["/api/whoami", "/api/dashboard"]);

    dashboard.resolve(DASHBOARD);
    await waitFor(() => {
      expect(byId("oldestBody")).toHaveTextContent("TicketCo");
    });

    expect(document.body).toHaveTextContent("Hunt funnel");
    expect(document.body).toHaveTextContent("Oldest open job");
    expect(byId("oldestBody")).toHaveTextContent("TicketCo");
    expect(byId("oldestBody")).toHaveTextContent("Staff");
    expect(byId("oldestBody")).toHaveTextContent("discovered");
    expect(byId("kpiOldestDays")).toHaveTextContent("4");
    expect(byId("kpiFoundToday")).toHaveTextContent("2");
    expect(byId("kpiAppliedToday")).toHaveTextContent("1");
    expect(byId("agentWorking")).toHaveTextContent("1");

    const funnel = [...document.querySelectorAll("h2")].find((node) => node.textContent === "Hunt funnel")?.closest("section");
    expect(funnel?.querySelector("#funnelLegend")).toBe(byId("funnelLegend"));
    expect(funnel?.querySelectorAll("[data-slot='card']")).toHaveLength(3);
    const legend = [...byId("funnelLegend").querySelectorAll("li")].map((item) => item.textContent?.replace(/\s+/g, " ").trim());
    expect(legend).toEqual(["Found 3", "Applied 1", "Outreached 0"]);
    expect((funnel?.querySelector("[data-funnel='Found']") as HTMLElement | null)?.style.width).toBe("100%");
    expect((funnel?.querySelector("[data-funnel='Applied']") as HTMLElement | null)?.style.width).toBe("33%");
    expect((funnel?.querySelector("[data-funnel='Outreached']") as HTMLElement | null)?.style.width).toBe("0%");

    expect(homeSource).not.toMatch(/chart\.js|chartjs|Chart/i);
    expect(homeSource).toContain('from "@/components/shell/AppShell"');
    expect(homeSource).toContain('from "@/lib/api"');
    expect(homeSource).toContain('from "@/lib/motion"');
    expect(homeSource).toContain("pageVariants(");
    expect(homeSource).toContain('from "@/components/ui/card"');
    expect(homeSource).toContain('scroll="page"');
    expect(homeSource).toContain('path="/home"');
    expect(pageVariants(true)).toEqual({
      initial: false,
      animate: { opacity: 1 },
      exit: { opacity: 0 },
    });
    const motionStyles = [...document.querySelectorAll<HTMLElement>("[style]")]
      .map((node) => node.getAttribute("style") ?? "")
      .join("\n");
    expect(motionStyles).not.toMatch(/translateY|translate3d/i);
  });

  it("uses an em dash when the pipeline is empty and falls back to actor and role", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") {
        return Promise.resolve({ actor: "scout", user_id: "user-2", role: "discovery" });
      }
      if (path === "/api/dashboard") {
        return Promise.resolve({
          funnel: { found: 0, applied: 0, outreached: 0 },
          agents: { total: 0, working: 0, live: 0 },
          today: { found: 0, applied: 0, day_start: "2026-11-20T00:00:00Z" },
          oldest_in_pipeline: null,
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HomePage />);

    await waitFor(() => {
      expect(byId("whoLabel")).toHaveTextContent("scout · discovery");
    });
    expect(byId("kpiFoundToday")).toHaveTextContent("0");
    expect(byId("kpiAppliedToday")).toHaveTextContent("0");
    expect(byId("kpiOldestDays")).toHaveTextContent("—");
    expect(byId("agentWorking")).toHaveTextContent("0");
    expect(byId("oldestBody")).not.toHaveTextContent("TicketCo");
    const legend = [...byId("funnelLegend").querySelectorAll("li")].map((item) => item.textContent?.replace(/\s+/g, " ").trim());
    expect(legend).toEqual(["Found 0", "Applied 0", "Outreached 0"]);
  });

  it("falls back to user id and kind", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") return Promise.resolve({ user_id: "user-3", kind: "agent" });
      if (path === "/api/dashboard") {
        return Promise.resolve({
          funnel: { found: 0, applied: 0, outreached: 0 },
          agents: { total: 0, working: 0, live: 0 },
          today: { found: 0, applied: 0, day_start: "2026-11-20T00:00:00Z" },
          oldest_in_pipeline: null,
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HomePage />);
    await waitFor(() => {
      expect(byId("whoLabel")).toHaveTextContent("user-3 · agent");
    });
  });

  it("keeps Home current when the window path is somewhere else", () => {
    window.history.replaceState({}, "", "/board");
    apiMock.mockImplementation(() => new Promise(() => {}));

    render(<HomePage />);

    expect(document.querySelector("[data-nav='/home']")).toHaveAttribute("aria-current", "page");
    expect(document.querySelector("[data-nav='/board']")).not.toHaveAttribute("aria-current", "page");
  });

  it("shows an em dash when the open job has no age", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") return Promise.resolve({ display_name: "Ada", kind: "owner" });
      if (path === "/api/dashboard") {
        return Promise.resolve({
          ...DASHBOARD,
          oldest_in_pipeline: { ...DASHBOARD.oldest_in_pipeline, days_in_pipeline: null },
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<HomePage />);

    await waitFor(() => {
      expect(byId("kpiOldestDays")).toHaveTextContent("—");
    });
    expect(byId("kpiOldestSub")).toHaveTextContent("Age unknown");
    expect(byId("oldestBody")).toHaveTextContent("TicketCo");
    expect(byId("oldestBody")).toHaveTextContent("Staff");
    expect(byId("oldestBody")).toHaveTextContent("discovered");
  });

  it("posts logout and leaves for /login", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") return Promise.resolve(WHO);
      if (path === "/api/dashboard") return Promise.resolve(DASHBOARD);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async () => new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<HomePage />);
    fireEvent.click(byId("logoutBtn"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toBe("/api/auth/logout");
    expect(call?.[1]?.method).toBe("POST");
    expect(call?.[1]?.credentials).toBe("same-origin");
    await waitFor(() => {
      expect(window.location.pathname).toBe("/login");
    });
  });

  it("stops after whoami when api rejects unauthorized", async () => {
    apiMock.mockRejectedValue(new Error("unauthorized"));
    render(<HomePage />);
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/whoami");
    });
    expect(apiMock.mock.calls.map((call) => call[0])).toEqual(["/api/whoami"]);
    expect(byId("connLabel")).toHaveTextContent("signing in");
    expect(byId("kpiFoundToday")).toHaveTextContent("—");
  });
});
