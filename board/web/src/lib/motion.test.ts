import { describe, expect, it } from "vitest";

import { pageVariants, panelVariants, sheetVariants } from "./motion";

describe("panelVariants", () => {
  it("keeps the first paint visible", () => {
    expect(panelVariants(false, false)).toEqual({ initial: false, animate: { opacity: 1 } });
    expect(panelVariants(true, false)).toEqual({ initial: false, animate: { opacity: 1 } });
  });

  it("fades a later panel without a transform when motion is reduced", () => {
    expect(panelVariants(true, true)).toEqual({ initial: { opacity: 0 }, animate: { opacity: 1 } });
    expect(pageVariants(true).animate).not.toHaveProperty("y");
  });

  it("slides a later panel when motion is allowed", () => {
    expect(panelVariants(false, true)).toEqual({
      initial: { opacity: 0, y: 8 },
      animate: { opacity: 1, y: 0 },
    });
  });
});

describe("sheetVariants", () => {
  it("fades a sheet without a transform when motion is reduced", () => {
    expect(sheetVariants(true)).toEqual({ initial: { opacity: 0 }, animate: { opacity: 1 } });
    expect(sheetVariants(true).initial).not.toHaveProperty("y");
  });

  it("raises a sheet when motion is allowed", () => {
    expect(sheetVariants(false)).toEqual({
      initial: { opacity: 0, y: 16 },
      animate: { opacity: 1, y: 0 },
    });
  });
});
