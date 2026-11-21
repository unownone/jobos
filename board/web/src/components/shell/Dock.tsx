import { LogOut, MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

import { logout } from "./logout";
import { DOCK_NAV, MORE_NAV } from "./nav";
import { NavLink } from "./NavLink";

const displayFont = "font-display text-[1.35rem] [font-family:var(--font-display)]";

export function Dock({ narrow, pathname }: { narrow: boolean; pathname: string }) {
  return (
    <nav
      aria-label="Primary"
      aria-hidden={narrow ? undefined : true}
      className="fixed inset-x-0 bottom-0 z-30 col-start-1 row-start-1 hidden max-[959px]:grid grid-cols-4 border-t border-dashed border-border bg-secondary pb-[env(safe-area-inset-bottom)]"
    >
      {DOCK_NAV.map((item) => (
        <NavLink key={item.href} item={item} pathname={pathname} layout="rail" />
      ))}
      <Sheet>
        <SheetTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            className="h-auto w-full flex-col gap-0.5 px-1 py-1.5 text-[0.65rem] font-semibold text-muted-foreground"
          >
            <MoreHorizontal aria-hidden="true" />
            More
          </Button>
        </SheetTrigger>
        <SheetContent side="bottom" aria-describedby="hub-more-desc">
          <SheetHeader>
            <SheetTitle className={displayFont}>More</SheetTitle>
          </SheetHeader>
          <p id="hub-more-desc" className="sr-only">
            Invites, data, skills, memory, candidate, and log out
          </p>
          <nav aria-label="More" className="flex flex-col gap-1">
            {MORE_NAV.map((item) => (
              <NavLink key={item.href} item={item} pathname={pathname} layout="row" />
            ))}
            <Button
              type="button"
              variant="ghost"
              data-hub-logout
              className="w-full justify-start gap-2 px-3 text-muted-foreground"
              onClick={() => {
                void logout();
              }}
            >
              <LogOut aria-hidden="true" />
              Log out
            </Button>
          </nav>
        </SheetContent>
      </Sheet>
    </nav>
  );
}
