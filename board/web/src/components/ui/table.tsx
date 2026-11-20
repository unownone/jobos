import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

function Table({ className, ...props }: ComponentProps<"table">) {
  return <table className={cn("w-full table-fixed text-left text-sm", className)} {...props} />;
}

function Th({ className, ...props }: ComponentProps<"th">) {
  return <th className={cn("px-3 py-2 font-medium", className)} {...props} />;
}

function Td({
  className,
  truncate = true,
  ...props
}: ComponentProps<"td"> & { truncate?: boolean }) {
  return (
    <td
      className={cn("px-3 py-2", truncate ? "max-w-0 truncate" : "whitespace-normal", className)}
      {...props}
    />
  );
}

export { Table, Td, Th };
