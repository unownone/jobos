import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LandingPage } from "./LandingPage";
import { StartPage } from "./StartPage";

function frameOf(container: HTMLElement): HTMLElement {
  const frame = container.firstElementChild;
  if (!(frame instanceof HTMLElement)) {
    throw new Error("missing frame");
  }
  return frame;
}

describe("LandingPage", () => {
  it("keeps the document from scrolling and offers the harness", () => {
    const { container } = render(<LandingPage />);
    const frame = frameOf(container);
    const main = screen.getByRole("main");

    expect(frame.className).toContain("overflow-hidden");
    expect(frame.className).toContain("h-dvh");
    expect(main.className).toContain("overflow-y-auto");
    expect(main.className).toContain("min-h-0");
    expect(main).toHaveAttribute("id", "main");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.queryByTestId("hub-frame")).not.toBeInTheDocument();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Find jobs");
    const login = screen.getByRole("link", { name: "Log in" });
    expect(login).toHaveAttribute("href", "/login");
    expect(login).toHaveAttribute("data-slot", "button");
    expect(login.className).toContain("bg-primary");

    const account = screen.getByRole("link", { name: "Log in or create an account" });
    expect(account).toHaveAttribute("href", "/login");
    expect(account).toHaveAttribute("data-slot", "button");

    const started = screen.getAllByRole("link", { name: "Get started" });
    expect(started.length).toBeGreaterThan(0);
    for (const link of started) {
      expect(link).toHaveAttribute("href", "/start");
    }
    const secondary = started.find((link) => link.getAttribute("data-slot") === "button");
    expect(secondary).toBeDefined();
    expect(secondary?.className).toContain("bg-secondary");

    expect(document.getElementById("capabilities")).toBeInTheDocument();
    expect(document.getElementById("loop")).toBeInTheDocument();
    expect(document.getElementById("start")).toBeInTheDocument();
    expect(document.getElementById("loop-rail")).toBeInTheDocument();
    expect(screen.getByText(/Discovery never Easy Applies/)).toBeInTheDocument();
    expect(screen.getByText(/Maintainer ≠ discovery/)).toBeInTheDocument();
    expect(main).toHaveTextContent("candidate_required");
  });
});

describe("StartPage", () => {
  it("states the candidate gate inside the same scroll frame", () => {
    const { container } = render(<StartPage />);
    const frame = frameOf(container);
    const main = screen.getByRole("main");

    expect(frame.className).toContain("overflow-hidden");
    expect(frame.className).toContain("h-dvh");
    expect(main.className).toContain("overflow-y-auto");
    expect(main.className).toContain("min-h-0");
    expect(main).toHaveAttribute("id", "main");
    expect(screen.queryByTestId("hub-frame")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Get started");
    expect(main).toHaveTextContent("candidate_required");
    expect(document.getElementById("coming-soon")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
    expect(screen.getByText(/Do not scrape Hub HTML/)).toBeInTheDocument();
  });
});

describe("signed-in public links", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("points login links at the board when the session is already valid", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ actor: "ada" }), { status: 200 })),
    );

    render(<LandingPage />);

    await waitFor(() => {
      expect(screen.getAllByRole("link", { name: "Open board" }).length).toBeGreaterThan(0);
    });
    for (const link of screen.getAllByRole("link", { name: "Open board" })) {
      expect(link).toHaveAttribute("href", "/board");
    }
    expect(screen.queryByRole("link", { name: "Log in" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Log in or create an account" })).not.toBeInTheDocument();
  });
});
