import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./badge";
import { Button } from "./button";
import { Field } from "./field";
import { RecordCard, RecordField } from "./record-card";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "./card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./dropdown-menu";
import { ScrollArea, ScrollBar } from "./scroll-area";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";
import { Separator } from "./separator";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "./sheet";
import { Toaster } from "./sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";

const uiDir = dirname(fileURLToPath(import.meta.url));

describe("hub primitives", () => {
  it("stacks a field label above its control", () => {
    render(<Field htmlFor="name">Name<input id="name" /></Field>);
    const label = screen.getByText("Name").closest("label");
    expect(label?.getAttribute("data-slot")).toBe("label");
    expect(label?.className).toContain("flex-col");
  });

  it("wraps a card value instead of clipping it", () => {
    render(
      <RecordCard title="Audit Fixture Co" subtitle="Staff Software Engineer">
        <RecordField label="ID" value="board__audit-fixture-co-staff-software-engineer" />
      </RecordCard>,
    );
    const value = screen.getByText("board__audit-fixture-co-staff-software-engineer");
    expect(value.className).toContain("break-all");
    expect(value.className).not.toContain("truncate");
    expect(screen.getByText("Audit Fixture Co").className).not.toContain("truncate");
  });

  it("gives Button a 44px touch target", () => {
    render(<Button>Apply</Button>);
    expect(screen.getByRole("button").className).toContain("min-h-[2.75rem]");
  });

  it("does not lock button or input to a sub-44px height", () => {
    const button = readFileSync(join(uiDir, "button.tsx"), "utf8");
    const input = readFileSync(join(uiDir, "input.tsx"), "utf8");
    for (const source of [button, input]) {
      expect(source).not.toContain("h-8");
      expect(source).not.toContain("h-9");
      expect(source).not.toContain("h-10");
    }
  });

  it("exports the primitives later tasks import", () => {
    const named = {
      Select,
      SelectGroup,
      SelectValue,
      SelectTrigger,
      SelectContent,
      SelectItem,
      DropdownMenu,
      DropdownMenuTrigger,
      DropdownMenuContent,
      DropdownMenuItem,
      DropdownMenuSeparator,
      ScrollArea,
      ScrollBar,
      Sheet,
      SheetTrigger,
      SheetContent,
      SheetHeader,
      SheetTitle,
      SheetClose,
      Tabs,
      TabsList,
      TabsTrigger,
      TabsContent,
      Badge,
      Card,
      CardHeader,
      CardTitle,
      CardContent,
      CardFooter,
      Separator,
      Dialog,
      DialogTrigger,
      DialogContent,
      DialogHeader,
      DialogTitle,
      DialogFooter,
      DialogClose,
      Toaster,
    };
    expect(
      Object.fromEntries(Object.entries(named).map(([name, value]) => [name, typeof value])),
    ).toEqual(Object.fromEntries(Object.keys(named).map((name) => [name, "function"])));
  });
});
