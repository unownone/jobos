import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { logout } from "./logout";

function connDotClass(conn: string): string {
  switch (conn) {
    case "signing in":
      return "bg-muted-foreground";
    case "signed in":
      return "bg-primary";
    case "sign in required":
      return "bg-destructive";
    default:
      return "bg-muted-foreground";
  }
}

export function TopBar({
  title,
  subtitle,
  who,
  conn,
}: {
  title: string;
  subtitle?: string;
  who?: string;
  conn?: string;
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
        {conn !== undefined ? (
          <span className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
            <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", connDotClass(conn))} />
            <span id="connLabel" className="truncate">
              {conn}
            </span>
          </span>
        ) : null}
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
