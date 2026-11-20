import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { JoinPage } from "./JoinPage";
import { OnboardingPage } from "./OnboardingPage";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const apiMock = vi.mocked(api);

beforeEach(() => {
  apiMock.mockReset();
  window.history.replaceState({}, "", "/onboarding");
});

function mockCandidate(put?: (body: unknown) => void) {
  apiMock.mockImplementation((path: string, opts?: { method?: string; body?: unknown; raw?: BodyInit | null; contentType?: string }) => {
    if (path === "/api/auth/me") return Promise.resolve({ kind: "admin", actor: "ada", user: { email: "ada@example.test" } });
    if (path === "/api/candidate" && opts?.method === "PUT") {
      put?.(opts.body);
      return Promise.resolve({ revision: "9" });
    }
    if (path === "/api/candidate") return Promise.resolve({});
    if (path === "/api/candidate/resume" && opts?.method === "PUT") return Promise.resolve({});
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

describe("OnboardingPage", () => {
  it("fills the form from the JSON profile envelope", async () => {
    apiMock.mockImplementation((path: string) => {
      if (path === "/api/auth/me") return Promise.resolve({ kind: "admin", actor: "ada", user: { email: "ada@example.test" } });
      if (path === "/api/candidate") {
        return Promise.resolve({
          profile: { identity: { full_name: "Ada Lovelace", email: "ada@example.test" } },
          revision: "blob-1",
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<OnboardingPage />);
    await waitFor(() => {
      expect(document.getElementById("full_name")).toHaveValue("Ada Lovelace");
    });
    expect(document.getElementById("email")).toHaveValue("ada@example.test");
    expect(document.getElementById("who")).toHaveTextContent("Signed in as ada@example.test");
    expect(document.getElementById("err")).toHaveTextContent("");
    expect(document.getElementById("revLine")).toHaveTextContent("revision blob-1");
  });

  it("blocks step 2 until name and email are present", async () => {
    mockCandidate();
    render(<OnboardingPage />);
    await waitFor(() => {
      expect(document.getElementById("who")).toHaveTextContent("ada@example.test");
    });
    fireEvent.click(document.getElementById("to2") as HTMLButtonElement);
    expect(document.getElementById("err")).toHaveTextContent("Full name and email");
    expect(document.getElementById("step2")).toHaveAttribute("hidden");
  });

  it("saves the profile and reveals the resume step", async () => {
    let saved: unknown;
    mockCandidate((body) => {
      saved = body;
    });
    render(<OnboardingPage />);
    await waitFor(() => expect(document.getElementById("full_name")).toBeInTheDocument());

    fireEvent.change(document.getElementById("full_name") as HTMLInputElement, { target: { value: "Ada Lovelace" } });
    fireEvent.change(document.getElementById("email") as HTMLInputElement, { target: { value: "ada@example.test" } });
    fireEvent.click(document.getElementById("to2") as HTMLButtonElement);
    expect(document.getElementById("step2")).not.toHaveAttribute("hidden");

    fireEvent.click(document.getElementById("to3") as HTMLButtonElement);
    expect(document.getElementById("err")).toHaveTextContent("title");

    fireEvent.change(document.getElementById("titles") as HTMLInputElement, { target: { value: "Staff Software Engineer" } });
    fireEvent.change(document.getElementById("locations_t") as HTMLInputElement, { target: { value: "Remote" } });
    fireEvent.click(document.getElementById("to3") as HTMLButtonElement);
    fireEvent.click(document.getElementById("save") as HTMLButtonElement);

    await waitFor(() => {
      expect(document.getElementById("ok")).toHaveTextContent("Profile saved");
    });
    expect(document.getElementById("step4")).not.toHaveAttribute("hidden");
    expect(saved).toMatchObject({
      identity: { full_name: "Ada Lovelace", email: "ada@example.test" },
      target: { titles: ["Staff Software Engineer"], locations: ["Remote"] },
    });
  });

  it("uploads the resume as raw pdf bytes and can skip to the board", async () => {
    mockCandidate();
    render(<OnboardingPage />);
    await waitFor(() => expect(document.getElementById("skipResume")).toBeInTheDocument());

    const pdf = new Uint8Array([0x25, 0x50, 0x44, 0x46]);
    const file = new File([pdf], "resume.pdf", { type: "application/pdf" });
    fireEvent.change(document.getElementById("resume") as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(document.getElementById("uploadResume") as HTMLButtonElement);

    await waitFor(() => {
      const call = apiMock.mock.calls.find((item) => item[0] === "/api/candidate/resume");
      expect(call?.[1]?.contentType).toBe("application/pdf");
      expect(call?.[1]?.raw).toBeInstanceOf(Uint8Array);
    });

    fireEvent.click(document.getElementById("skipResume") as HTMLButtonElement);
    await waitFor(() => {
      expect(window.location.pathname).toBe("/board");
    });
  });
});

describe("JoinPage", () => {
  it("says onboarding is incomplete and shows the API key after register", async () => {
    window.history.replaceState({}, "", "/join/inv1?s=secret");
    const fetchMock = vi.fn(async (path: RequestInfo | URL, init?: RequestInit) => {
      const url = String(path);
      if (url.startsWith("/api/join/")) {
        return new Response(JSON.stringify({ track: "discovery", mode: "owner_then_agents", join_blocked: true, candidate: { onboarded: false } }), { status: 200 });
      }
      if (url === "/api/auth/join") {
        return new Response(JSON.stringify({ kind: "agent", track: "discovery", api_key: "jh_agt_once" }), { status: 200 });
      }
      return new Response("no", { status: 500, statusText: init?.method || "GET" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = render(<JoinPage />);
    expect(document.querySelector("h1")).toHaveTextContent("Join");
    expect(document.getElementById("payload")?.className).toContain("break-all");
    expect(document.getElementById("key")?.className).toContain("break-all");
    await waitFor(() => {
      expect(document.getElementById("blurb")).toHaveTextContent("Candidate onboarding");
    });
    unmount();

    fetchMock.mockImplementation(async (path: RequestInfo | URL) => {
      const url = String(path);
      if (url.startsWith("/api/join/")) {
        return new Response(JSON.stringify({ track: "discovery", mode: "owner_then_agents", candidate: { onboarded: true } }), { status: 200 });
      }
      if (url === "/api/auth/join") {
        return new Response(JSON.stringify({ kind: "agent", track: "discovery", api_key: "jh_agt_once" }), { status: 200 });
      }
      return new Response("no", { status: 500 });
    });
    render(<JoinPage />);
    await waitFor(() => {
      expect(document.getElementById("form")).not.toHaveAttribute("hidden");
    });
    fireEvent.change(document.getElementById("name") as HTMLInputElement, { target: { value: "Scout" } });
    fireEvent.submit(document.getElementById("form") as HTMLFormElement);
    await waitFor(() => {
      expect(document.getElementById("key")).toHaveTextContent("API key");
    });
    expect(document.getElementById("key")).toHaveTextContent("jh_agt_once");
  });
});
