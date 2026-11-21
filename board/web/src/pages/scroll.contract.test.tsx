import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

import { BoardPage } from "./BoardPage";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
}));

const apiMock = vi.mocked(api);

function classOf(node: Element | null): string {
  return node instanceof HTMLElement ? node.className : "";
}

describe("scroll contract", () => {
  it("gives the job list its own scrollport and keeps the pager outside it", async () => {
    apiMock.mockRejectedValue(new Error("unauthorized"));
    render(<BoardPage />);
    await waitFor(() => {
      expect(document.getElementById("list")).toBeTruthy();
    });

    const frame = document.querySelector("[data-testid='hub-frame']");
    const list = document.getElementById("list");
    const pager = document.getElementById("pager");
    if (!(frame instanceof HTMLElement) || !(list instanceof HTMLElement) || !(pager instanceof HTMLElement)) {
      throw new Error("missing board shell");
    }

    expect(classOf(frame)).toContain("overflow-hidden");
    expect(classOf(frame)).toContain("h-dvh");
    expect(classOf(list)).toContain("overflow-y-auto");
    expect(list.contains(pager)).toBe(false);

    let node: HTMLElement | null = list.parentElement;
    while (node && node !== frame) {
      const classes = classOf(node);
      const clips = classes.includes("overflow-hidden") && classes.includes("h-dvh");
      expect(clips).toBe(false);
      node = node.parentElement;
    }
  });
});
