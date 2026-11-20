import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";
import { SignupPage } from "./SignupPage";

type FetchInput = RequestInfo | URL;

function requestUrl(input: FetchInput): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(routes: Record<string, (init: RequestInit | undefined) => Response>) {
  return vi.fn(async (input: FetchInput, init?: RequestInit) => {
    const url = requestUrl(input);
    const handler = routes[url];
    if (!handler) {
      throw new Error(`unexpected ${url}`);
    }
    return handler(init);
  });
}

function header(init: RequestInit | undefined, name: string): string | null {
  const headers = new Headers(init?.headers);
  return headers.get(name);
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  window.localStorage.clear();
  document.cookie = "hub_csrf=; Max-Age=0";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LoginPage", () => {
  it("renders the username field and the Create account button", () => {
    const { container } = render(<LoginPage />);
    const username = document.getElementById("username");
    const signup = document.getElementById("signupBtn");
    const card = container.querySelector("[data-slot='card']");

    expect(username).toBeInstanceOf(HTMLInputElement);
    expect(username).toHaveAttribute("data-slot", "input");
    expect(document.getElementById("form")).toBeInstanceOf(HTMLFormElement);
    expect(document.getElementById("password")).toHaveAttribute("data-slot", "input");
    expect(document.getElementById("err")).toBeInTheDocument();
    expect(signup).toHaveAttribute("data-slot", "button");
    expect(signup).toHaveTextContent("Create account");
    expect(card?.className).toContain("max-w-md");
    expect(card?.parentElement?.className).toContain("place-items-center");
    expect(container.querySelector("[data-testid='hub-frame']")).not.toBeInTheDocument();
  });

  it("goes to onboarding when the candidate is not onboarded", async () => {
    document.cookie = "hub_csrf=abc%3D123";
    window.history.replaceState({}, "", "/login?next=/admin/memory");
    const fetchMock = mockFetch({
      "/api/auth/login": () => jsonResponse({ ok: true }, 200),
      "/api/candidate/status": () => jsonResponse({ candidate_onboarded: false }, 200),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPage />);
    fireEvent.change(document.getElementById("username")!, { target: { value: "ada" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "secret" } });
    fireEvent.submit(document.getElementById("form")!);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/onboarding");
    });

    const loginCall = fetchMock.mock.calls.find((call) => requestUrl(call[0]) === "/api/auth/login");
    expect(loginCall).toBeDefined();
    const init = loginCall?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect(header(init, "X-CSRF")).toBe("abc=123");
    expect(init?.body).toBe(JSON.stringify({ username: "ada", password: "secret" }));
    expect(window.location.search).toBe("");
  });

  it("keeps a wrong password on the form", async () => {
    window.history.replaceState({}, "", "/login");
    const fetchMock = mockFetch({
      "/api/auth/login": () => jsonResponse({ detail: "invalid username or password" }, 401),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPage />);
    fireEvent.change(document.getElementById("username")!, { target: { value: "ada" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "nope" } });
    fireEvent.submit(document.getElementById("form")!);

    await waitFor(() => {
      expect(document.getElementById("err")).toHaveTextContent("invalid username or password");
    });
    expect(window.location.pathname).toBe("/login");
    expect(window.location.search).toBe("");
    expect(fetchMock.mock.calls.map((call) => requestUrl(call[0]))).toEqual(["/api/auth/login"]);
  });

  it("follows next after an onboarded candidate and maps /start to the board", async () => {
    window.history.replaceState({}, "", "/login?next=/start");
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "/api/auth/login": () => jsonResponse({ ok: true }, 200),
        "/api/candidate/status": () => jsonResponse({ candidate_onboarded: true }, 200),
      }),
    );

    render(<LoginPage />);
    fireEvent.change(document.getElementById("username")!, { target: { value: "ada" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "secret" } });
    fireEvent.submit(document.getElementById("form")!);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/board");
    });
  });

  it("reads the live candidate status field onboarded", async () => {
    window.history.replaceState({}, "", "/login?next=/admin/memory");
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "/api/auth/login": () => jsonResponse({ ok: true }, 200),
        "/api/candidate/status": () => jsonResponse({ onboarded: false }, 200),
      }),
    );

    render(<LoginPage />);
    fireEvent.change(document.getElementById("username")!, { target: { value: "ada" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "secret" } });
    fireEvent.submit(document.getElementById("form")!);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/onboarding");
    });
  });

  it("creates an account without leaving on a taken username", async () => {
    window.history.replaceState({}, "", "/login");
    const fetchMock = mockFetch({
      "/api/auth/signup": () => jsonResponse({ detail: "username already taken" }, 409),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPage />);
    fireEvent.change(document.getElementById("username")!, { target: { value: "ada" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "secret" } });
    fireEvent.click(document.getElementById("signupBtn")!);

    await waitFor(() => {
      expect(document.getElementById("err")).toHaveTextContent("username already taken");
    });
    const signupCall = fetchMock.mock.calls.find((call) => requestUrl(call[0]) === "/api/auth/signup");
    expect(signupCall?.[1]?.credentials).toBe("same-origin");
    expect(signupCall?.[1]?.body).toBe(JSON.stringify({ username: "ada", password: "secret" }));
    expect(window.location.pathname).toBe("/login");
  });
});

describe("SignupPage", () => {
  it("posts the bootstrap secret from the hash and opens onboarding", async () => {
    document.cookie = "hub_csrf=tok";
    window.history.replaceState({}, "", "/admin/signup#bootstrap=jh_boot_test");
    const fetchMock = mockFetch({
      "/api/auth/bootstrap": () => jsonResponse({ ok: true }, 200),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(<SignupPage />);
    const token = document.getElementById("token");
    expect(token).toBeInstanceOf(HTMLInputElement);
    expect(token).toHaveAttribute("data-slot", "input");
    expect((token as HTMLInputElement).value).toBe("jh_boot_test");
    expect(document.getElementById("email")).toHaveAttribute("data-slot", "input");
    expect(document.getElementById("password")).toBeInstanceOf(HTMLInputElement);
    expect(document.getElementById("err")).toBeInTheDocument();
    expect(container.querySelector("[data-slot='card']")?.className).toContain("max-w-md");
    expect(container.querySelector("[data-testid='hub-frame']")).not.toBeInTheDocument();

    fireEvent.change(document.getElementById("email")!, { target: { value: "ada@example.com" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "long-secret" } });
    fireEvent.submit(document.getElementById("form")!);

    await waitFor(() => {
      expect(window.location.pathname).toBe("/onboarding");
    });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect(header(init, "X-CSRF")).toBe("tok");
    expect(init?.body).toBe(
      JSON.stringify({ email: "ada@example.com", password: "long-secret", token: "jh_boot_test" }),
    );
  });

  it("keeps a rejected bootstrap token on the form", async () => {
    window.history.replaceState({}, "", "/admin/signup");
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "/api/auth/bootstrap": () => jsonResponse({ detail: "invalid or used bootstrap token" }, 403),
      }),
    );

    render(<SignupPage />);
    fireEvent.change(document.getElementById("email")!, { target: { value: "ada@example.com" } });
    fireEvent.change(document.getElementById("password")!, { target: { value: "long-secret" } });
    fireEvent.change(document.getElementById("token")!, { target: { value: "nope" } });
    fireEvent.submit(document.getElementById("form")!);

    await waitFor(() => {
      expect(document.getElementById("err")).toHaveTextContent("invalid or used bootstrap token");
    });
    expect(window.location.pathname).toBe("/admin/signup");
  });
});
