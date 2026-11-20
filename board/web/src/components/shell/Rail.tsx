import { ScrollArea } from "@/components/ui/scroll-area";

import { NAV } from "./nav";
import { NavLink } from "./NavLink";

export function Rail({ narrow, pathname }: { narrow: boolean; pathname: string }) {
  return (
    <nav
      aria-label="Hub"
      aria-hidden={narrow ? true : undefined}
      className="sticky top-0 flex h-full min-h-0 flex-col gap-1 border-r border-dashed border-border bg-secondary px-1.5 py-3 text-foreground max-[959px]:hidden"
    >
      <a href="/home" className="mx-auto mb-2 grid size-11 shrink-0 place-items-center">
        <span className="grid size-[2.35rem] place-items-center overflow-hidden">
          <img
            src="/brand/mascot.png"
            width={36}
            height={36}
            alt="jobOS"
            className="size-[4.3rem] max-w-none object-cover"
          />
        </span>
      </a>
      <ScrollArea className="min-h-0 w-full flex-1 overflow-hidden">
        <div className="flex flex-col gap-0.5">
          {NAV.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} layout="rail" />
          ))}
        </div>
      </ScrollArea>
    </nav>
  );
}
