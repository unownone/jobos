import * as SheetPrimitive from "@radix-ui/react-dialog";
import { motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import type { ComponentProps, HTMLAttributes } from "react";

import { sheetVariants, usePageTransition } from "@/lib/motion";
import { cn } from "@/lib/utils";

const sheetSides = {
  top: "inset-x-0 top-0 border-b",
  bottom: "inset-x-0 bottom-0 border-t",
  left: "inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm",
  right: "inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm",
} as const;

type SheetSide = keyof typeof sheetSides;

function Sheet(props: ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root {...props} />;
}

function SheetTrigger({ className, ...props }: ComponentProps<typeof SheetPrimitive.Trigger>) {
  return (
    <SheetPrimitive.Trigger
      data-slot="sheet-trigger"
      className={cn("min-h-[2.75rem]", className)}
      {...props}
    />
  );
}

function SheetClose({ className, ...props }: ComponentProps<typeof SheetPrimitive.Close>) {
  return (
    <SheetPrimitive.Close
      data-slot="sheet-close"
      className={cn("min-h-[2.75rem]", className)}
      {...props}
    />
  );
}

function SheetContent({
  className,
  children,
  side = "right",
  ...props
}: ComponentProps<typeof SheetPrimitive.Content> & { side?: SheetSide }) {
  const reduce = useReducedMotion() === true;
  const variants = sheetVariants(reduce);
  const transition = usePageTransition();
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay data-slot="sheet-overlay" className="fixed inset-0 z-50 bg-background/80" />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        className={cn(
          "fixed z-50 flex flex-col gap-4 overflow-hidden bg-popover p-6 text-popover-foreground shadow-lg border border-border",
          sheetSides[side],
          className,
        )}
        {...props}
      >
        <motion.div
          className="flex min-h-0 flex-1 flex-col"
          initial={variants.initial}
          animate={variants.animate}
          transition={transition}
        >
          {children}
        </motion.div>
        <SheetClose className="absolute top-3 right-3 inline-flex items-center justify-center rounded-md opacity-70 transition-colors hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring min-w-[2.75rem]">
          <X className="size-4" />
          <span className="sr-only">Close</span>
        </SheetClose>
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  );
}

function SheetHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div data-slot="sheet-header" className={cn("flex flex-col gap-1.5", className)} {...props} />;
}

function SheetTitle({ className, ...props }: ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn("text-lg font-semibold text-foreground", className)}
      {...props}
    />
  );
}

export { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle, SheetTrigger };
