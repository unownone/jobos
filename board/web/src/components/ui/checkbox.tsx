import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

function Checkbox({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="checkbox"
      data-slot="checkbox"
      className={cn("size-5 shrink-0 accent-primary", className)}
      {...props}
    />
  );
}

export { Checkbox };
