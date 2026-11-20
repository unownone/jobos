import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { isCurrent, type NavItem } from "./nav";

type NavLayout = "rail" | "row";

function layoutClass(layout: NavLayout): string {
  switch (layout) {
    case "rail":
      return "w-full flex-col gap-0.5 px-1 py-1.5 text-[0.65rem]";
    case "row":
      return "w-full justify-start gap-2 px-3";
    default: {
      const exhaustive: never = layout;
      return exhaustive;
    }
  }
}

export function NavLink({
  item,
  pathname,
  layout,
}: {
  item: NavItem;
  pathname: string;
  layout: NavLayout;
}) {
  const Icon = item.icon;
  const active = isCurrent(item.href, pathname);
  return (
    <Button
      variant="ghost"
      asChild
      className={cn(
        "h-auto font-semibold text-muted-foreground hover:text-foreground aria-[current=page]:bg-accent aria-[current=page]:text-accent-foreground",
        layoutClass(layout),
      )}
    >
      <a href={item.href} data-nav={item.href} aria-current={active ? "page" : undefined}>
        <Icon aria-hidden="true" />
        {item.label}
      </a>
    </Button>
  );
}
