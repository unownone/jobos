import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("keeps the document from scrolling and gives the page a scrollport", () => {
    render(
      <AppShell title="jobOS Harness" subtitle="helps find jobs" scroll="page">
        <p>Hunt funnel</p>
      </AppShell>,
    );
    const frame = screen.getByTestId("hub-frame");
    const port = screen.getByTestId("hub-scroll");
    expect(frame.className).toContain("overflow-hidden");
    expect(frame.className).toContain("h-dvh");
    expect(port.className).toContain("overflow-y-auto");
    expect(port.className).toContain("min-h-0");
    const hub = screen.getByRole("navigation", { name: "Hub" });
    expect(hub).toBeInTheDocument();
    expect(hub.textContent).not.toMatch(/Log out/);
    expect(document.querySelectorAll("#logoutBtn")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Directory" })).toHaveAttribute("href", "/admin/users");
    expect(screen.getByText("helps find jobs")).toBeInTheDocument();
  });

  it("does not scroll the stage when panes own the scroll", () => {
    render(
      <AppShell title="jobOS Harness" scroll="panes">
        <div>list</div>
      </AppShell>,
    );
    expect(screen.getByTestId("hub-scroll").className).not.toContain("overflow-y-auto");
  });
});
