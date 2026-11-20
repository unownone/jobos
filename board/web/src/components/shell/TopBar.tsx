import { Button } from "@/components/ui/button";

import { logout } from "./logout";

export function TopBar({
  title,
  subtitle,
  who,
}: {
  title: string;
  subtitle?: string;
  who?: string;
}) {
  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-dashed border-primary bg-card px-4 py-2">
      <div className="min-w-0">
        <h1 className="truncate font-display text-[1.35rem] leading-none font-extrabold tracking-[-0.03em] [font-family:var(--font-display)]">
          {title}
        </h1>
        {subtitle ? <p className="truncate text-sm text-muted-foreground">{subtitle}</p> : null}
      </div>
      <div className="flex min-w-0 items-center justify-end gap-2">
        <span id="whoLabel" className="truncate text-sm text-muted-foreground">
          {who}
        </span>
        <Button
          id="logoutBtn"
          type="button"
          variant="outline"
          data-hub-logout
          className="shrink-0"
          onClick={() => {
            void logout();
          }}
        >
          Log out
        </Button>
      </div>
    </header>
  );
}
