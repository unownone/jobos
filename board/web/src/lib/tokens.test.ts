import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../index.css"),
  "utf8",
);

describe("terminal-ops tokens", () => {
  it("maps shadcn variables onto the chassis palette", () => {
    expect(css).toContain("--background: #0b1220");
    expect(css).toContain("--foreground: #f3eee3");
    expect(css).toContain("--card: #172033");
    expect(css).toContain("--primary: #e0992d");
    expect(css).toContain("--primary-foreground: #0b1220");
    expect(css).toContain("--muted-foreground: #cbb892");
    expect(css).toContain("--destructive: #c45c4a");
    expect(css).toContain("--ring: #e0992d");
    expect(css).toContain("--radius: 2px");
  });
});