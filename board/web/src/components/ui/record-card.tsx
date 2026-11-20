import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Card } from "./card";

function RecordDeck({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div data-slot="record-deck" className={cn("flex flex-col gap-2 min-[721px]:hidden", className)}>
      {children}
    </div>
  );
}

function RecordCard({
  title,
  subtitle,
  onClick,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  onClick?: () => void;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const body = (
    <Card className="p-3">
      <p className="m-0 break-words font-medium" title={title}>
        {title}
      </p>
      {subtitle ? (
        <p className="m-0 mt-1 break-words text-sm text-muted-foreground" title={subtitle}>
          {subtitle}
        </p>
      ) : null}
      {children ? <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">{children}</dl> : null}
      {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
    </Card>
  );
  if (!onClick) return body;
  return (
    <button type="button" className="min-h-11 w-full text-left" onClick={onClick}>
      {body}
    </button>
  );
}

function RecordField({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 break-all" title={value}>
        {value}
      </dd>
    </>
  );
}

export { RecordCard, RecordDeck, RecordField };
