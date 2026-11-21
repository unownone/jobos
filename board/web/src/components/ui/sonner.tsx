import type { CSSProperties } from "react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

import { cn } from "@/lib/utils";

function Toaster({ toastOptions, style, className, ...props }: ToasterProps) {
  return (
    <Sonner
      theme="dark"
      className={cn("toaster group", className)}
      toastOptions={{
        ...toastOptions,
        classNames: {
          ...toastOptions?.classNames,
          toast: cn(
            "bg-popover text-popover-foreground border-border",
            toastOptions?.classNames?.toast,
          ),
          closeButton: cn("min-h-[2.75rem] min-w-[2.75rem]", toastOptions?.classNames?.closeButton),
        },
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          ...style,
        } as CSSProperties
      }
      {...props}
    />
  );
}

export { Toaster };
