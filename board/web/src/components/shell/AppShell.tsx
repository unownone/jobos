import { useEffect, useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { cn } from "@/lib/utils";
import { pageVariants, usePageTransition } from "@/lib/motion";

import { Dock } from "./Dock";
import { Rail } from "./Rail";
import { TopBar, type ShellConn } from "./TopBar";

export type ShellScroll = "page" | "panes";

const frameClass =
  "grid h-dvh overflow-hidden bg-background text-foreground grid-cols-[5.5rem_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] max-[959px]:grid-cols-1 max-[959px]:pb-[calc(3.5rem+env(safe-area-inset-bottom))]";

function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 959px)");
    const apply = () => setNarrow(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  return narrow;
}

function scrollPortClass(scroll: ShellScroll): string | undefined {
  switch (scroll) {
    case "page":
      return "overflow-y-auto overflow-x-hidden";
    case "panes":
      // Clip the stage so the wheel stays on the panes. Do not scroll this port.
      return "overflow-hidden";
    default: {
      const exhaustive: never = scroll;
      return exhaustive;
    }
  }
}

function motionClass(scroll: ShellScroll): string {
  switch (scroll) {
    case "page":
      return "flex flex-col";
    case "panes":
      return "flex min-h-0 min-w-0 flex-1 flex-col";
    default: {
      const exhaustive: never = scroll;
      return exhaustive;
    }
  }
}

export function AppShell({
  title,
  subtitle,
  scroll,
  who,
  conn,
  path,
  children,
}: {
  title: string;
  subtitle?: string;
  scroll: ShellScroll;
  who?: string;
  conn?: ShellConn;
  path?: string;
  children: ReactNode;
}) {
  const narrow = useNarrowViewport();
  const pathname = path ?? (typeof window === "undefined" ? "/" : window.location.pathname);
  const reduceMotion = useReducedMotion() === true;
  const variants = pageVariants(reduceMotion);
  const transition = usePageTransition();

  return (
    <div data-testid="hub-frame" className={frameClass}>
      <Rail narrow={narrow} pathname={pathname} />
      <div className="flex min-h-0 min-w-0 flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:z-40 focus:m-2 focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
        >
          Skip to content
        </a>
        <TopBar title={title} subtitle={subtitle} who={who} conn={conn} />
        <div
          data-testid="hub-scroll"
          className={cn("flex min-h-0 min-w-0 flex-1 flex-col", scrollPortClass(scroll))}
        >
          <motion.div
            className={motionClass(scroll)}
            initial={variants.initial}
            animate={variants.animate}
            exit={variants.exit}
            transition={transition}
          >
            {children}
          </motion.div>
        </div>
      </div>
      <Dock narrow={narrow} pathname={pathname} />
    </div>
  );
}
