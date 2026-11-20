import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { DataPage } from "./DataPage";
import { InvitesPage } from "./InvitesPage";
import { MemoryPage } from "./MemoryPage";
import { SkillsPage } from "./SkillsPage";
import { UsersPage } from "./UsersPage";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const apiMock = vi.mocked(api);

beforeEach(() => {
  apiMock.mockReset();
});

describe("admin pages", () => {
  it("renders the invite track control and shows the join link", async () => {
    apiMock.mockImplementation((path: string, opts?: { method?: string }) => {
      if (path === "/api/auth/me") return Promise.resolve({ user: { email: "ada@example.test" }, actor: "ada" });
      if (path === "/api/invites" && opts?.method === "POST") {
        return Promise.resolve({ join_url: "https://hub.example/join/inv1?s=secret", agent_prompt: "curl the hub" });
      }
      if (path === "/api/invites") return Promise.resolve({ invites: [{ id: "inv1", track: "discovery", mode: "owner_then_agents", revoked: false }] });
      if (path === "/api/meta") return Promise.resolve({ coming_soon_roles: [{ id: "review", summary: "feedback" }] });
      if (path === "/api/presence/heartbeat") return Promise.resolve({});
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<InvitesPage />);

    expect(document.body).toHaveTextContent("jobOS Harness");
    expect(document.getElementById("track")?.tagName).toBe("SELECT");
    expect(document.getElementById("track")).toHaveAttribute("name", "track");
    expect(document.getElementById("track")).toHaveAttribute("data-slot", "select");
    expect(document.getElementById("multi")?.tagName).toBe("INPUT");
    expect(document.getElementById("multi")).toHaveAttribute("name", "multi");
    expect(document.getElementById("multi")).toHaveAttribute("data-slot", "checkbox");
    expect(document.querySelector("[data-testid='hub-scroll']")?.className).toContain("overflow-y-auto");

    fireEvent.click(document.getElementById("multi") as HTMLInputElement);
    fireEvent.submit(document.getElementById("form") as HTMLFormElement);

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/invites", expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({ allow_multiple_owners: true }),
      }));
      expect(document.getElementById("created")).toHaveTextContent("/join/");
    });
    expect(document.getElementById("url")).toHaveTextContent("/join/inv1");
    await waitFor(() => {
      expect(document.getElementById("rows")).toHaveTextContent("discovery");
    });
  });

  it("shows revoked when the invite carries revoked_at", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada" });
      if (path === "/api/invites") {
        return Promise.resolve({
          invites: [{ id: "inv1", track: "outreach", mode: "owner_then_agents", revoked_at: "2026-11-20T00:00:00Z" }],
        });
      }
      if (path === "/api/meta") return Promise.resolve({ coming_soon_roles: [] });
      if (path === "/api/presence/heartbeat") return Promise.resolve({});
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<InvitesPage />);

    await waitFor(() => {
      expect(document.getElementById("rows")).toHaveTextContent("revoked");
    });
    expect(document.getElementById("rows")).not.toHaveTextContent("Revoke");
  });

  it("lists directory rows", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/users") {
        return Promise.resolve({ users: [{ user_id: "u1", display_name: "Ada", kind: "admin", status: "offline" }] });
      }
      if (path === "/api/presence/heartbeat") return Promise.resolve({});
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<UsersPage />);

    expect(document.body).toHaveTextContent("Directory");
    expect(document.querySelectorAll("#logoutBtn")).toHaveLength(1);
    await waitFor(() => {
      expect(document.getElementById("rows")).toHaveTextContent("Ada");
    });
    expect([...document.querySelectorAll("th")].find((header) => header.textContent === "Last active")?.className).toContain("w-[14%]");
    expect([...document.querySelectorAll("th")].find((header) => header.textContent === "Task")?.className).toContain("w-[18%]");
  });

  it("names a directory lane without an empty track", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/users") {
        return Promise.resolve({
          users: [
            {
              user_id: "u1",
              display_name: "Ada",
              role: "admin",
              last_active: "Last active: just now",
              current_task: { id: "board__audit-fixture-co-staff-software-engineer" },
            },
            { user_id: "u2", display_name: "Bea", track: "discovery", role: "owner", last_seen: "2h ago" },
          ],
        });
      }
      if (path === "/api/presence/heartbeat") return Promise.resolve({});
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<UsersPage />);
    await waitFor(() => {
      expect(document.getElementById("rows")).toHaveTextContent("Ada");
    });
    const ada = [...document.querySelectorAll("#rows tr")].find((row) => row.textContent?.includes("Ada"));
    expect(ada?.textContent).toContain("admin");
    expect(ada?.textContent).not.toContain("/ admin");
    expect(ada?.textContent).toContain("just now");
    expect(ada?.textContent).not.toContain("Last active:");
    const task = ada?.querySelectorAll("td")[8];
    expect(task?.textContent).toBe("board__audit-fixture-co-staff-software-engineer");
    expect(task?.className).toContain("break-all");
    expect(task?.className).not.toContain("truncate");
    const bea = [...document.querySelectorAll("#rows tr")].find((row) => row.textContent?.includes("Bea"));
    expect(bea?.textContent).toContain("discovery / owner");
    expect(bea?.textContent).toContain("2h ago");
    expect(apiMock).toHaveBeenCalledWith("/api/presence/heartbeat", {
      method: "POST",
      body: { status_hint: "logged_in" },
    });
  });

  it("names a job card by company", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada" });
      if (path.startsWith("/api/jobs")) {
        return Promise.resolve({
          jobs: [{ id: "board__acme", company: "Acme", title: "Engineer", status: "discovered", stopped: true, score: 4 }],
          count: 1,
          total: 1,
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<DataPage />);
    await waitFor(() => {
      expect(document.querySelector("[data-slot='record-deck'] p")?.textContent).toBe("Acme");
    });
    expect(document.querySelector("#table th")?.textContent).toBe("ID");
    expect(document.querySelector("#table td")?.className).toContain("break-all");
    expect([...document.querySelectorAll("#table th")].find((header) => header.textContent === "Title")?.className).toContain("w-[28%]");
    expect([...document.querySelectorAll("#table td")][2]?.className).toContain("break-words");
    expect([...document.querySelectorAll("#table td")][3]?.textContent).toBe("discovered · stopped");
    expect([...document.querySelectorAll("#table td")][3]?.className).toContain("break-words");
  });

  it("wraps a hosted connector path", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada" });
      if (path.startsWith("/api/jobs")) return Promise.resolve({ jobs: [], count: 0, total: 0 });
      if (path.startsWith("/api/onboarding")) {
        return Promise.resolve({
          connectors_needed: [{ id: "gmail", required: true, hosted: "/api/mcp/hosted/google-workspace.json", reason: "Mail" }],
          mcp_example: "gmail",
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<DataPage />);
    fireEvent.click(document.querySelector("[data-tab='mcps']") as HTMLButtonElement);
    await waitFor(() => {
      expect(document.getElementById("table")).toHaveTextContent("/api/mcp/hosted/google-workspace.json");
    });
    const hosted = [...document.querySelectorAll("#table td")].find((cell) => cell.textContent === "/api/mcp/hosted/google-workspace.json");
    expect(hosted?.className).toContain("break-all");
    expect(hosted?.className).not.toContain("truncate");
  });

  it("renders the data browser", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/jobs")) return Promise.resolve({ jobs: [], count: 0, total: 0 });
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada" });
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<DataPage />);

    expect(document.querySelector("h1")).toHaveTextContent("jobOS data");
    expect(document.getElementById("tabs")).toBeInTheDocument();
    expect(document.getElementById("q")?.closest("label")?.className).toContain("w-56");
    expect(document.getElementById("q")?.closest("label")).toHaveTextContent("Search");
    expect(document.getElementById("status")).toBeInTheDocument();
    expect(document.getElementById("stopped")?.tagName).toBe("SELECT");
    expect(document.getElementById("stopped")).toHaveAttribute("data-slot", "select");
    expect(document.getElementById("stopped")?.className).toContain("w-auto");
    expect(document.getElementById("go")).toBeInTheDocument();
    expect(document.getElementById("table")).toBeInTheDocument();
  });

  it("labels the data skill filters", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada" });
      if (path.startsWith("/api/jobs")) return Promise.resolve({ jobs: [], count: 0, total: 0 });
      if (path.startsWith("/api/registry/skills")) return Promise.resolve({ skills: [], count: 0 });
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<DataPage />);
    fireEvent.click(document.querySelector("[data-tab='skills']") as HTMLButtonElement);
    await waitFor(() => {
      expect(document.getElementById("tag")?.parentElement).toHaveTextContent("Tag");
    });
    expect(document.getElementById("tag")?.hasAttribute("aria-label")).toBe(false);
    expect(document.getElementById("tag")?.closest("label")?.className).toContain("w-44");
    expect(document.getElementById("scope")?.parentElement).toHaveTextContent("Scope");
  });

  it("opens the data tab named in the query", async () => {
    window.history.replaceState({}, "", "/admin/data?tab=memory");
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada" });
      if (path.startsWith("/api/jobs")) return Promise.resolve({ jobs: [], count: 0, total: 0 });
      if (path.startsWith("/api/memory/items")) {
        return Promise.resolve({
          items: [{ id: "m1", pod: "track:discovery", kind: "search_coverage", title: "E2E Wellfound pagination", body: "Public search" }],
          count: 1,
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    try {
      render(<DataPage />);
      await waitFor(() => {
        expect(document.getElementById("table")).toHaveTextContent("Wellfound");
      });
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });

  it("seeds the skill registry", async () => {
    apiMock.mockImplementation((path: string, opts?: { method?: string }) => {
      if (path === "/api/auth/me") return Promise.resolve({ display_name: "Ada", kind: "admin" });
      if (path.startsWith("/api/registry/skills")) return Promise.resolve({ skills: [{ slug: "hunt", role: "discovery", tags: ["source"], scope: "shared", status: "active" }] });
      if (path === "/api/registry/recordings") return Promise.resolve({ recordings: [] });
      if (path === "/api/registry/seed" && opts?.method === "POST") return Promise.resolve({ counts: { skills: 2 } });
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<SkillsPage />);

    expect(document.querySelector("h1")).toHaveTextContent("Skill registry");
    await waitFor(() => {
      expect(document.getElementById("who")).toHaveTextContent("Ada · admin");
    });
    expect(document.getElementById("tag")?.parentElement).toHaveTextContent("Tag");
    expect(document.getElementById("tag")?.hasAttribute("aria-label")).toBe(false);
    expect(document.getElementById("scope")?.parentElement).toHaveTextContent("Scope");
    fireEvent.change(document.getElementById("tag") as HTMLSelectElement, { target: { value: "source" } });
    await waitFor(() => {
      expect(apiMock.mock.calls.some((call) => String(call[0]).includes("tag=source"))).toBe(true);
    });
    expect(document.getElementById("skills")?.closest("table")?.className).toContain("table-fixed");
    expect(document.querySelectorAll("#logout")).toHaveLength(0);
    expect(document.querySelectorAll("#logoutBtn")).toHaveLength(1);
    fireEvent.click(document.getElementById("seed") as HTMLButtonElement);

    await waitFor(() => {
      expect(document.getElementById("msg")).toHaveTextContent("Seeded");
    });
  });

  it("wraps a skill recording id and note", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ display_name: "Ada", kind: "admin" });
      if (path.startsWith("/api/registry/skills")) return Promise.resolve({ skills: [] });
      if (path === "/api/registry/recordings") {
        return Promise.resolve({
          recordings: [{
            id: "rec_board__audit-fixture-co-staff-software-engineer",
            skill: "job-discovery",
            scope: "shared",
            status: "recorded",
            note: "Portal quirk: the apply form rejects a resume unless the content type is application/pdf.",
          }],
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<SkillsPage />);
    await waitFor(() => {
      expect(document.getElementById("recordings")).toHaveTextContent("Portal quirk");
    });
    const cells = [...document.querySelectorAll("#recordings td")];
    expect(cells[0]?.textContent).toBe("rec_board__audit-fixture-co-staff-software-engineer");
    expect(cells[0]?.className).toContain("break-all");
    expect(cells[0]?.className).not.toContain("truncate");
    const note = cells[4];
    expect(note?.className).toContain("break-words");
    expect(note?.className).not.toContain("max-[959px]:hidden");
    expect(note?.className).not.toContain("truncate");
  });

  it("names the skill registry from the session user", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") {
        return Promise.resolve({
          role: "admin",
          actor: "auditoperator",
          kind: "admin",
          user: { display_name: "auditoperator" },
        });
      }
      if (path.startsWith("/api/registry/skills")) return Promise.resolve({ skills: [] });
      if (path === "/api/registry/recordings") return Promise.resolve({ recordings: [] });
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<SkillsPage />);

    await waitFor(() => {
      expect(document.getElementById("who")).toHaveTextContent("auditoperator · admin");
    });
    expect(document.getElementById("who")).not.toHaveTextContent("admin · admin");
  });

  it("stores a memory fact and solidifies it", async () => {
    apiMock.mockImplementation((path: string, opts?: { method?: string }) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada", role: "admin" });
      if (path === "/api/memory/pods") {
        return Promise.resolve({
          pods: [{ id: "track:discovery", label: "discovery", writable: true }],
          kinds: { track: ["portal"] },
          write_policy: { store_when: "When it will matter next round.", caps: { track: 4 } },
        });
      }
      if (path === "/api/memory/items" && opts?.method === "POST") return Promise.resolve({ status: "stored", id: "mem1" });
      if (path.startsWith("/api/memory/items?")) {
        return Promise.resolve({
          items: [{ id: "mem1", pod: "track:discovery", kind: "portal", title: "Lever", body: "Use the public board.", pod_scope: "track", solidify_status: "none" }],
        });
      }
      if (path === "/api/memory/items/mem1/solidify") return Promise.resolve({});
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<MemoryPage />);

    expect(document.querySelector("h1")).toHaveTextContent("Memory pods");
    await waitFor(() => {
      expect(document.getElementById("policy")).toHaveTextContent("15-minute caps: track 4");
    });
    expect(document.getElementById("policy")?.textContent).not.toContain("{");
    expect(document.getElementById("add-item")).toBeInTheDocument();
    expect(document.getElementById("write-title")?.parentElement?.parentElement).toBe(
      document.getElementById("write-company")?.parentElement?.parentElement,
    );
    expect(document.getElementById("write-body")?.parentElement?.className).toContain("md:col-span-2");

    fireEvent.change(document.getElementById("write-title") as HTMLInputElement, { target: { value: "Lever" } });
    fireEvent.change(document.getElementById("write-body") as HTMLTextAreaElement, { target: { value: "Use the public board." } });
    fireEvent.click(document.getElementById("add-item") as HTMLButtonElement);

    await waitFor(() => {
      expect(document.getElementById("compose-status")).toHaveTextContent("Stored");
    });
    await waitFor(() => {
      expect(document.querySelector("[data-solidify='mem1']")).toBeInTheDocument();
    });
    const podCell = [...document.querySelectorAll("#rows td")].find((cell) => cell.textContent === "track:discovery");
    expect(podCell?.className).toContain("break-all");

    fireEvent.click(document.querySelector("[data-solidify='mem1']") as HTMLButtonElement);

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/memory/items/mem1/solidify", { method: "POST" });
    });
  });

  it("uses a kind the selected pod allows", async () => {
    apiMock.mockImplementation((path: string, opts?: { method?: string; body?: { kind?: string } }) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada", role: "admin" });
      if (path === "/api/memory/pods") {
        return Promise.resolve({
          pods: [
            { id: "worker:ada", label: "worker", writable: true },
            { id: "track:discovery", label: "discovery", writable: true },
          ],
          kinds: { worker: ["fact"], track: ["portal_quirk"] },
          write_policy: { store_when: "When it will matter next round.", caps: {} },
        });
      }
      if (path.startsWith("/api/memory/items?")) return Promise.resolve({ items: [] });
      if (path === "/api/memory/items" && opts?.method === "POST") return Promise.resolve({ status: "stored", id: "mem2" });
      return Promise.reject(new Error(`unexpected ${path}`));
    });

    render(<MemoryPage />);
    await waitFor(() => expect((document.getElementById("write-kind") as HTMLSelectElement).value).toBe("fact"));

    fireEvent.change(document.getElementById("write-pod") as HTMLSelectElement, { target: { value: "track:discovery" } });
    expect((document.getElementById("write-kind") as HTMLSelectElement).value).toBe("portal_quirk");
    fireEvent.change(document.getElementById("write-title") as HTMLInputElement, { target: { value: "Greenhouse" } });
    fireEvent.change(document.getElementById("write-body") as HTMLTextAreaElement, { target: { value: "Page two asks." } });
    fireEvent.click(document.getElementById("add-item") as HTMLButtonElement);

    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/memory/items", expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({ pod: "track:discovery", kind: "portal_quirk" }),
      }));
    });
  });

  it("edits, shares, and deletes a memory row", async () => {
    apiMock.mockImplementation((path: string, opts?: { method?: string; body?: unknown }) => {
      if (path === "/api/auth/me") return Promise.resolve({ actor: "ada", role: "admin" });
      if (path === "/api/memory/pods") {
        return Promise.resolve({
          pods: [
            { id: "track:discovery", label: "discovery", writable: true },
            { id: "common", label: "common", writable: true },
          ],
          kinds: { track: ["portal"], common: ["portal"] },
          write_policy: { store_when: "When it will matter next round.", caps: {} },
        });
      }
      if (path.startsWith("/api/memory/items?")) {
        return Promise.resolve({
          items: [{ id: "mem1", pod: "track:discovery", kind: "portal", title: "Lever", body: "Use the public board.", pod_scope: "track", solidify_status: "none" }],
        });
      }
      if (path === "/api/memory/items/mem1" && opts?.method === "PATCH") return Promise.resolve({ item: {} });
      if (path === "/api/memory/items/mem1" && opts?.method === "DELETE") return Promise.resolve({});
      if (path === "/api/memory/items/mem1/move") return Promise.resolve({ item: {} });
      return Promise.reject(new Error(`unexpected ${path} ${opts?.method ?? "GET"}`));
    });

    render(<MemoryPage />);
    await waitFor(() => expect(document.querySelector("[data-edit='mem1']")).toBeInTheDocument());
    expect(document.querySelector("button[data-edit]")?.getAttribute("data-edit")).toBe("mem1");

    fireEvent.click(document.querySelector("[data-edit='mem1']") as HTMLButtonElement);
    expect(document.getElementById("compose-status")).toHaveTextContent("Editing.");
    fireEvent.change(document.getElementById("write-title") as HTMLInputElement, { target: { value: "Lever public" } });
    fireEvent.click(document.getElementById("save-item") as HTMLButtonElement);
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/memory/items/mem1", {
        method: "PATCH",
        body: { title: "Lever public", body: "Use the public board." },
      });
      expect(document.getElementById("compose-status")).toHaveTextContent("Updated");
    });

    fireEvent.click(document.querySelector("[data-share='mem1']") as HTMLButtonElement);
    fireEvent.click(document.getElementById("share-go") as HTMLButtonElement);
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/memory/items/mem1/move", {
        method: "POST",
        body: { pod: "track:discovery", copy: false, kind: "portal" },
      });
    });

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(document.querySelector("[data-delete='mem1']") as HTMLButtonElement);
    await waitFor(() => {
      expect(apiMock).toHaveBeenCalledWith("/api/memory/items/mem1", { method: "DELETE" });
    });
  });
});
