import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { BoardPage } from "./BoardPage";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const apiMock = vi.mocked(api);

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

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

beforeEach(() => {
  apiMock.mockReset();
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
    for (const id of ["pager", "moreFilters", "list", "q", "logoutBtn", "whoLabel", "connLabel"]) {
      expect(document.getElementById(id)).toBeInTheDocument();
    }
    expect(document.getElementById("connLabel")).toHaveTextContent("signing in");
    expect(document.body).not.toHaveTextContent("Select a job");
    expect(document.getElementById("connectForm")).not.toBeInTheDocument();
    expect(document.getElementById("list")?.contains(document.getElementById("pager"))).toBe(false);
    expect(document.querySelector("[data-testid='hub-scroll']")?.className).toContain("overflow-hidden");
  });

  it("opens a ticket from the list and saves the allowed fields", async () => {
    apiMock.mockImplementation((path: string, opts?: { method?: string; body?: unknown }) => {
      if (path === "/api/whoami") {
        return Promise.resolve({
          user: { display_name: "Ada" },
          kind: "owner",
          role: "admin",
          can_patch: true,
          patch_fields: ["company", "title", "status"],
        });
      }
      if (path === "/api/meta") return Promise.resolve({ statuses: ["discovered"], apply_kinds: ["portal"] });
      if (path.startsWith("/api/jobs?")) {
        return Promise.resolve({
          jobs: [JOB],
          count: 1,
          total: 4,
          matched: 2,
          limit: 25,
          offset: 0,
          role: "admin",
        });
      }
      if (path === "/api/jobs/1" && opts?.method === "PATCH") return Promise.resolve({});
      if (path === "/api/jobs/1") return Promise.resolve({ job: JOB });
      if (path.startsWith("/api/events")) return Promise.resolve({ events: [] });
      if (path === "/api/presence/heartbeat") return Promise.resolve({});
      if (path === "/api/presence") return Promise.resolve({ users: [] });
      if (path.startsWith("/api/queue")) return Promise.resolve({ items: [{ kind: "apply", status: "ready" }] });
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<BoardPage />);

    await waitFor(() => {
      expect(document.getElementById("list")).toHaveTextContent("TicketCo");
    });
    expect(document.getElementById("stats")).toHaveTextContent("1 shown · 2 match · 4 total · admin");
    expect(document.getElementById("pageLabel")).toHaveTextContent("Page 1 of 1");
    const jobsCall = apiMock.mock.calls.find((call) => String(call[0]).startsWith("/api/jobs?"));
    expect(String(jobsCall?.[0])).toContain("limit=25");
    expect(String(jobsCall?.[0])).toContain("offset=0");

    fireEvent.click(document.querySelector("#list tbody tr") as HTMLElement);

    await waitFor(() => {
      expect(document.getElementById("f_company")).toHaveValue("TicketCo");
    });
    expect(document.body).toHaveTextContent("Rejected by");

    fireEvent.change(document.getElementById("f_title") as HTMLInputElement, { target: { value: "Staff Engineer" } });
    fireEvent.click(document.getElementById("saveBtn") as HTMLButtonElement);

    await waitFor(() => {
      expect(document.getElementById("sideErr")).toHaveTextContent("Saved.");
    });
    const patch = apiMock.mock.calls.find((call) => call[0] === "/api/jobs/1" && call[1]?.method === "PATCH");
    expect(patch?.[1]?.body).toEqual({ company: "TicketCo", title: "Staff Engineer", status: "discovered" });
  });
});
