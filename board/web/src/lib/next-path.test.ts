import { afterEach, describe, expect, it, vi } from "vitest";
import { nextPath } from "./next-path";

describe("nextPath", () => {
  it("sends the public root to the board", () => {
    expect(nextPath("/")).toBe("/board");
    expect(nextPath(null)).toBe("/board");
    expect(nextPath("")).toBe("/board");
    expect(nextPath("//evil.example")).toBe("/board");
  });

  it("keeps an in-app path", () => {
    expect(nextPath("/admin/memory")).toBe("/admin/memory");
  });

  it("sends the public start page to the board", () => {
    expect(nextPath("/start")).toBe("/board");
  });

  it("rejects destinations that leave this origin", () => {
    expect(nextPath("/\\evil.example")).toBe("/board");
    expect(nextPath("/\\\\evil.example")).toBe("/board");
    expect(nextPath("https://evil.example/board")).toBe("/board");
    expect(nextPath("/%2F%2Fevil.example")).toBe("/board");
    expect(nextPath("/%5Cevil.example")).toBe("/board");
  });

  it("keeps a query on an in-app path", () => {
    expect(nextPath("/admin/memory?q=1")).toBe("/admin/memory?q=1");
  });
});