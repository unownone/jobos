import type { LabelHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

import { Label } from "./label";

function Field({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <Label className={cn("flex flex-col gap-1 font-normal", className)} {...props} />;
}

export { Field };
