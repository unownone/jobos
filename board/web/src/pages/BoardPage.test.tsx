import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { BoardPage } from "./BoardPage";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const apiMock = vi.mocked(api);

const TICKET_IDS = [
  "f_company",
  "f_title",
  "f_source",
  "f_status",
  "f_score",
  "f_location",
  "f_apply_url",
  "f_posted_at",
  "f_pay",
  "f_description",
  "f_expectations",
  "f_notes",
  "f_rejection_by",
  "f_company_remarks",
  "f_user_remarks",
  "f_owners",
  "f_apply_packet",
  "f_outreach_packet",
  "f_proof",
  "saveBtn",
  "pauseBtn",
  "stopBtn",
  "resumeBtn",
  "delBtn",
  "sideErr",
  "closeSide",
] as const;

const JOB = {
  id: "1",
  company: "TicketCo",
  title: "Staff",
  status: "discovered",
  stopped: false,
  sources: ["board"],
  location: "",
  apply_url: "",
  pay: "",
  posted_at: "",
  description: "",
  expectations: "",
  notes: "",
  score: null,
  rejection: { by: "", company_remarks: "", user_remarks: "" },
  owners: {},
  apply_packet: {},
  outreach_packet: {},
  proof: {},
};

const ADMIN = {
  user: { display_name: "Ada" },
  kind: "owner",
  role: "admin",
  can_patch: true,
  can_stop: true,
  can_delete: true,
  can_hygiene: true,
  patch_fields: ["company", "title", "status"],
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
  if (!(node instanceof HTMLElement)) throw new Error(`missing #${id}`);
  return node;
}

function installMatchMedia(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

function setBox(element: Element, heights: { client?: number; offset?: number }) {
  if (heights.client !== undefined) {
    Object.defineProperty(element, "clientHeight", { configurable: true, get: () => heights.client });
  }
  if (heights.offset !== undefined) {
    Object.defineProperty(element, "offsetHeight", { configurable: true, get: () => heights.offset });
  }
}

function listPayload(jobs: unknown[], matched = jobs.length === 0 ? 0 : 2) {
  return {
    jobs,
    count: jobs.length,
    total: 4,
    matched,
    limit: 25,
    offset: 0,
    role: "admin",
  };
}

function mockBoard(jobs: unknown[] = [JOB]) {
  apiMock.mockImplementation((path: string, opts?: { method?: string; body?: unknown }) => {
    if (path === "/api/whoami") return Promise.resolve(ADMIN);
    if (path === "/api/meta") return Promise.resolve({ statuses: ["discovered", "rejected"], apply_kinds: ["ats"] });
    if (path.startsWith("/api/jobs?")) return Promise.resolve(listPayload(jobs));
    if (path === "/api/jobs/1" && opts?.method === "PATCH") return Promise.resolve({});
    if (path === "/api/jobs/1" && opts?.method === "DELETE") return Promise.resolve({});
    if (path === "/api/jobs/1/pause" || path === "/api/jobs/1/stop" || path === "/api/jobs/1/resume") return Promise.resolve({});
    if (path === "/api/jobs/1") return Promise.resolve({ job: jobs[0] ?? JOB });
    if (path.startsWith("/api/events")) return Promise.resolve({ events: [] });
    if (path === "/api/presence/heartbeat") return Promise.resolve({ memory: { items: [] } });
    if (path === "/api/presence") return Promise.resolve({ users: [] });
    if (path.startsWith("/api/queue")) return Promise.resolve({ items: [{ kind: "apply", status: "ready" }] });
    return Promise.reject(new Error(`unexpected ${path} ${opts?.method ?? "GET"}`));
  });
}

beforeEach(() => {
  window.history.replaceState({}, "", "/home");
  apiMock.mockReset();
  vi.restoreAllMocks();
});

afterEach(() => {
  Reflect.deleteProperty(window, "matchMedia");
});

describe("BoardPage", () => {
  it("shows the board chrome before whoami returns", () => {
    const whoami = deferred<unknown>();
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") return whoami.promise;
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<BoardPage />);

    expect(document.body).toHaveTextContent("jobOS Harness");
    expect(document.body).toHaveTextContent("helps find jobs");
    expect(document.getElementById("statusBtn")).toHaveTextContent("All statuses");
    expect(document.getElementById("moreFilters")?.className).toContain("min-[960px]:flex");
    for (const id of ["pager", "moreFilters", "list", "q", "logoutBtn", "whoLabel", "connLabel", "side", "main"]) {
      expect(document.getElementById(id), id).toBeInTheDocument();
    }
    expect(document.querySelectorAll("#logoutBtn")).toHaveLength(1);
    expect(document.querySelectorAll("#connLabel")).toHaveLength(1);
    expect(byId("connLabel")).toHaveTextContent("signing in");
    expect(byId("list")).toHaveTextContent("Loading jobs…");
    expect(document.body).not.toHaveTextContent("Select a job");
    expect(document.getElementById("connectForm")).not.toBeInTheDocument();
    expect(byId("list").contains(byId("pager"))).toBe(false);
    expect(byId("stopped").tagName).toBe("SELECT");
    expect(byId("stopped").getAttribute("data-slot")).toBe("select");
    expect(byId("pageSize").tagName).toBe("SELECT");
    expect(byId("presenceRail").className).toContain("overflow-y-auto");
    expect(byId("presenceRail").className).toContain("max-[959px]:hidden");
    expect(document.querySelector("[data-nav='/board']")).toHaveAttribute("aria-current", "page");
    expect(document.querySelector("[data-testid='hub-scroll']")?.className).toContain("overflow-hidden");
    expect(document.querySelector("[data-testid='hub-scroll']")?.className).not.toContain("overflow-y-auto");
  });

  it("opens a ticket from the list and saves the allowed fields", async () => {
    mockBoard();
    render(<BoardPage />);

    await waitFor(() => {
      expect(byId("list")).toHaveTextContent("TicketCo");
    });
    expect(byId("whoLabel")).toHaveTextContent("Ada · owner");
    expect(byId("connLabel")).toHaveTextContent("signed in");
    expect(byId("stats")).toHaveTextContent("1 shown · 2 match · 4 total · admin");
    expect(byId("pageLabel")).toHaveTextContent("Page 1 of 1");
    const jobsCall = apiMock.mock.calls.find((call) => String(call[0]).startsWith("/api/jobs?"));
    expect(String(jobsCall?.[0])).toBe("/api/jobs?limit=25&offset=0");
    expect(byId("list").querySelector("thead")?.className).toContain("sticky");
    expect(byId("list").querySelector("thead")?.className).toContain("top-0");
    expect(byId("list").querySelector("[data-slot='badge']")?.className).toContain("border-dashed");

    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);

    await waitFor(() => {
      expect(byId("f_company")).toHaveValue("TicketCo");
    });
    expect(byId("side").tagName).toBe("ASIDE");
    expect(byId("side").className).toContain("min-w-0");
    expect(byId("side").querySelector("h2")?.textContent).toBe("TicketCo");
    expect(byId("side").querySelector("h2")?.className).toContain("truncate");
    expect(byId("side").querySelector("p")?.textContent).toBe(JOB.id);
    expect(byId("list").querySelector("table")?.className).toContain("table-fixed");
    expect([...byId("list").querySelectorAll("th")].find((header) => header.textContent === "Score")?.className).toContain("max-[959px]:hidden");
    expect(byId("list").contains(byId("pager"))).toBe(false);
    expect(byId("main").contains(byId("pager"))).toBe(false);
    expect(byId("main").contains(byId("list"))).toBe(true);
    for (const id of TICKET_IDS) expect(document.getElementById(id), id).toBeInTheDocument();
    expect(document.querySelector("label[for='f_rejection_by']")).toHaveTextContent("Rejected by");
    expect(byId("locationFilter").className).toContain("w-44");
    expect(byId("sourceFilter").className).toContain("w-44");
    expect(byId("f_status").tagName).toBe("SELECT");
    expect(byId("f_status").getAttribute("data-slot")).toBe("select");
    expect(byId("f_rejection_by").tagName).toBe("SELECT");
    expect(byId("side").querySelector("[data-slot='scroll-area']")).toBeTruthy();
    expect(byId("side").querySelector("[data-slot='scroll-area']")?.contains(byId("f_status"))).toBe(true);
    expect(byId("side").querySelector("[data-slot='scroll-area']")?.contains(byId("saveBtn"))).toBe(false);
    expect(byId("side").contains(byId("saveBtn"))).toBe(true);
    expect(document.querySelectorAll("#f_company")).toHaveLength(1);

    fireEvent.change(byId("f_title"), { target: { value: "Staff Engineer" } });
    fireEvent.click(byId("saveBtn"));

    await waitFor(() => {
      expect(byId("sideErr")).toHaveTextContent("Saved.");
    });
    const patch = apiMock.mock.calls.find((call) => call[0] === "/api/jobs/1" && call[1]?.method === "PATCH");
    expect(patch?.[1]?.body).toEqual({ company: "TicketCo", title: "Staff Engineer", status: "discovered" });
  });

  it("says there are no jobs after an empty page loads", async () => {
    mockBoard([]);
    render(<BoardPage />);
    expect(byId("list")).toHaveTextContent("Loading jobs…");
    await waitFor(() => {
      expect(byId("list")).toHaveTextContent("No jobs on this page.");
    });
    expect(byId("stats")).toHaveTextContent("0 shown · 0 match · 4 total · admin");
    expect(document.body).not.toHaveTextContent("Select a job");
  });

  it("sends a filter only when it is set", async () => {
    mockBoard();
    render(<BoardPage />);
    await waitFor(() => {
      expect(apiMock.mock.calls.some((call) => String(call[0]) === "/api/jobs?limit=25&offset=0")).toBe(true);
    });
    fireEvent.change(byId("locationFilter"), { target: { value: "Berlin" } });
    await waitFor(() => {
      expect(apiMock.mock.calls.some((call) => String(call[0]).includes("location=Berlin"))).toBe(true);
    });
    const filtered = apiMock.mock.calls.map((call) => String(call[0])).filter((url) => url.includes("location=Berlin")).at(-1);
    expect(filtered).toContain("limit=25");
    expect(filtered).toContain("offset=0");
    expect(filtered).not.toContain("status=");
    expect(filtered).not.toContain("lane=");
    expect(filtered).not.toContain("has_pay=");
  });

  it("keeps the pager outside the list and scrolls the stage only when the list would be under 8rem", async () => {
    mockBoard();
    render(<BoardPage />);
    await waitFor(() => expect(byId("list")).toHaveTextContent("TicketCo"));

    const stage = document.querySelector("[data-board-stage]");
    const toolbar = document.querySelector("[data-board-toolbar]");
    if (!(stage instanceof HTMLElement) || !(toolbar instanceof HTMLElement) || !stage.parentElement) {
      throw new Error("missing board stage");
    }
    expect(byId("list").contains(byId("pager"))).toBe(false);
    expect(stage.contains(byId("pager"))).toBe(true);
    expect(byId("main").contains(byId("list"))).toBe(true);

    setBox(stage.parentElement, { client: 900 });
    setBox(toolbar, { offset: 40 });
    setBox(byId("moreFilters"), { offset: 40 });
    setBox(byId("pager"), { offset: 40 });
    window.dispatchEvent(new Event("resize"));
    await waitFor(() => {
      expect(stage.className).not.toContain("overflow-y-auto");
    });
    expect(stage.className).toContain("overflow-hidden");
    expect(byId("main").className).toContain("min-h-0");
    expect(byId("main").className).toContain("flex-1");
    expect(byId("list").className).toContain("overflow-y-auto");
    expect(document.querySelector("[data-testid='hub-scroll']")?.className).not.toContain("overflow-y-auto");

    setBox(stage.parentElement, { client: 140 });
    window.dispatchEvent(new Event("resize"));
    await waitFor(() => {
      expect(stage.className).toContain("overflow-y-auto");
    });
    expect(byId("main").className).toContain("min-h-[8rem]");
    expect(byId("list").contains(byId("pager"))).toBe(false);
  });

  it("opens the ticket in a bottom sheet below 960px", async () => {
    installMatchMedia(true);
    mockBoard();
    render(<BoardPage />);
    await waitFor(() => expect(byId("list")).toHaveTextContent("TicketCo"));
    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);
    await waitFor(() => expect(byId("f_company")).toHaveValue("TicketCo"));
    expect(byId("side").getAttribute("data-slot")).toBe("sheet-content");
    expect(byId("side").className).toContain("bottom-0");
    expect(document.querySelectorAll("#f_company")).toHaveLength(1);
    expect(document.querySelector("aside#side")).not.toBeInTheDocument();
  });

  it("posts pause, stop, and delete with the live prompts", async () => {
    mockBoard();
    render(<BoardPage />);
    await waitFor(() => expect(byId("list")).toHaveTextContent("TicketCo"));
    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);
    await waitFor(() => expect(byId("pauseBtn")).toBeEnabled());

    const prompt = vi.spyOn(window, "prompt").mockReturnValue("hold");
    fireEvent.click(byId("pauseBtn"));
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/jobs/1/pause", { method: "POST", body: { reason: "hold" } });
    });
    expect(prompt).toHaveBeenCalledWith("Pause reason (required). Status stays; lanes cannot patch until Resume.");

    prompt.mockReturnValue("");
    fireEvent.click(byId("stopBtn"));
    expect(prompt).toHaveBeenCalledWith("Stop reason (required). Sets closed_withdrawn and freezes the row.");
    expect(apiMock.mock.calls.some((call) => call[0] === "/api/jobs/1/stop")).toBe(false);

    prompt.mockReturnValue("done");
    fireEvent.click(byId("stopBtn"));
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/jobs/1/stop", { method: "POST", body: { reason: "done" } });
    });

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(byId("delBtn"));
    expect(confirm).toHaveBeenCalledWith("Delete 1? This cannot be undone.");
    expect(apiMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);
    confirm.mockReturnValue(true);
    fireEvent.click(byId("delBtn"));
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/jobs/1", { method: "DELETE" });
    });
  });

  it("resumes a stopped row with POST and no reason", async () => {
    mockBoard([{ ...JOB, stopped: true }]);
    render(<BoardPage />);
    await waitFor(() => expect(byId("list")).toHaveTextContent("TicketCo"));
    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);
    await waitFor(() => expect(byId("resumeBtn")).toBeEnabled());
    expect(byId("pauseBtn")).toBeDisabled();
    expect(byId("stopBtn")).toBeDisabled();
    fireEvent.click(byId("resumeBtn"));
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/jobs/1/resume", { method: "POST" });
    });
  });

  it("heartbeats logged in, then working on the open job, and loads the queue for an admin", async () => {
    mockBoard();
    render(<BoardPage />);
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/presence/heartbeat", {
        method: "POST",
        body: { status_hint: "logged_in" },
      });
    });
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/presence");
    });
    await waitFor(() => {
      expect(byId("queueStats")).toHaveTextContent("apply:ready");
    });

    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);
    await waitFor(() => expect(byId("f_company")).toHaveValue("TicketCo"));
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/presence/heartbeat", {
        method: "POST",
        body: { status_hint: "working", task_id: "1", task_kind: "job", job_id: "1" },
      });
    });
  });

  it("does not load the queue for a lane worker", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/whoami") return Promise.resolve({ actor: "scout", role: "discovery" });
      if (path === "/api/meta") return Promise.resolve({ statuses: ["discovered"], apply_kinds: [] });
      if (path.startsWith("/api/jobs?")) return Promise.resolve(listPayload([]));
      if (path === "/api/presence/heartbeat") return Promise.resolve({ memory: { items: [] } });
      if (path === "/api/presence") return Promise.resolve({ users: [] });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<BoardPage />);
    await waitFor(() => expect(byId("whoLabel")).toHaveTextContent("scout · discovery"));
    await waitFor(() => expect(byId("list")).toHaveTextContent("No jobs on this page."));
    expect(apiMock.mock.calls.some((call) => String(call[0]).startsWith("/api/queue"))).toBe(false);
  });

  it("refuses a save when a JSON field does not parse", async () => {
    mockBoard();
    render(<BoardPage />);
    await waitFor(() => expect(byId("list")).toHaveTextContent("TicketCo"));
    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);
    await waitFor(() => expect(byId("f_owners")).toBeInTheDocument());
    fireEvent.change(byId("f_owners"), { target: { value: "{" } });
    fireEvent.click(byId("saveBtn"));
    await waitFor(() => {
      expect(byId("sideErr").textContent ?? "").not.toBe("");
    });
    expect(byId("sideErr").textContent).not.toBe("Saved.");
    expect(apiMock.mock.calls.some((call) => call[1]?.method === "PATCH")).toBe(false);
  });
});
