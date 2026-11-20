import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { logout } from "./logout";

export type ShellConn = "signing in" | "signed in" | "sign in required";

function connDotClass(conn: ShellConn): string {
  switch (conn) {
    case "signing in":
      return "bg-muted-foreground";
    case "signed in":
      return "bg-primary";
    case "sign in required":
      return "bg-destructive";
    default: {
      const exhaustive: never = conn;
      return exhaustive;
    }
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
  conn?: ShellConn;
}) {
  return (
    <header className="flex shrink-0 flex-col gap-2 border-b border-dashed border-primary bg-card px-4 py-2 min-[960px]:flex-row min-[960px]:items-center min-[960px]:justify-between">
      <div className="min-w-0">
        <h1 className="truncate font-display text-[1.35rem] leading-none font-extrabold tracking-[-0.03em] [font-family:var(--font-display)]">
          {title}
        </h1>
        {subtitle ? <p className="truncate text-sm text-muted-foreground">{subtitle}</p> : null}
      </div>
      <div className="flex min-w-0 items-center justify-between gap-2 min-[960px]:justify-end">
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
