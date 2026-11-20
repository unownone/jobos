import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const display =
  "font-display tracking-[-0.03em] [font-family:var(--font-display)]";

const sectionTitle = `${display} mb-3 text-[1.6rem] leading-none font-extrabold`;

const valueClass = `${display} m-0 text-[2.6rem] leading-none font-extrabold`;

type Dashboard = {
  funnel: { found: number; applied: number; outreached: number };
  agents: { total: number; working: number; live: number };
  today: { found: number; applied: number; day_start: string };
  oldest_in_pipeline: null | {
    id: string;
    company: string;
    title: string;
    status: string;
    location: string;
    pay: string;
    posted_at: string;
    created_at: string;
    days_in_pipeline: number;
    posted_known: boolean;
  };
};

type Whoami = {
  display_name?: string | null;
  actor?: string | null;
  user_id?: string | null;
  kind?: string | null;
  role?: string | null;
  user?: { display_name?: string | null } | null;
};

type Conn = "signing in" | "signed in" | "sign in required";

type OldestJob = NonNullable<Dashboard["oldest_in_pipeline"]>;

const FUNNEL_STAGES = [
  { key: "found", label: "Found" },
  { key: "applied", label: "Applied" },
  { key: "outreached", label: "Outreached" },
] as const;

function text(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

function formatWho(me: Whoami): string {
  const name = text(me.display_name) || text(me.user?.display_name) || text(me.actor) || text(me.user_id);
  const lane = text(me.kind) || text(me.role);
  return `${name} · ${lane}`;
}

function countText(value: number | undefined): string {
  if (value === undefined) return "—";
  return String(value);
}

function oldestDays(dashboard: Dashboard | undefined): string {
  if (!dashboard?.oldest_in_pipeline) return "—";
  return String(dashboard.oldest_in_pipeline.days_in_pipeline);
}

function oldestHint(dashboard: Dashboard | undefined): string {
  if (!dashboard) return "Open jobs only · posted date when known";
  const oldest = dashboard.oldest_in_pipeline;
  if (!oldest) return "No open jobs in the pipeline";
  if (oldest.days_in_pipeline === 1) return "1 day in pipeline";
  return `${oldest.days_in_pipeline} days in pipeline`;
}

function funnelMax(funnel: Dashboard["funnel"]): number {
  return Math.max(funnel.found, funnel.applied, funnel.outreached);
}

function barWidth(count: number, max: number): string {
  if (max <= 0) return "0%";
  return `${Math.round((count / max) * 100)}%`;
}

function dayLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toISOString().slice(0, 10);
}

function connDotClass(conn: Conn): string {
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

function Kpi({
  label,
  valueId,
  value,
  hint,
  hintId,
}: {
  label: string;
  valueId: string;
  value: string;
  hint: string;
  hintId?: string;
}) {
  return (
    <Card className="p-4">
      <p className="m-0 text-sm text-muted-foreground">{label}</p>
      <p id={valueId} className={`${valueClass} mt-2`}>
        {value}
      </p>
      <p id={hintId} className="mt-2 mb-0 text-sm text-muted-foreground">
        {hint}
      </p>
    </Card>
  );
}

function OldestBody({ job }: { job: OldestJob }) {
  return (
    <div>
      <p className={`${display} m-0 text-[1.8rem] leading-none font-extrabold`}>{job.company}</p>
      <p className="mt-2 mb-0 flex flex-wrap items-center gap-2">
        <span>{job.title}</span>
        <Badge variant="outline" className="border-dashed border-current">
          {job.status}
        </Badge>
      </p>
      <p className="mt-3 mb-0 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
        <span>{job.posted_at ? `Posted ${dayLabel(job.posted_at)}` : "Posted date unknown"}</span>
        {job.created_at ? <span>found {dayLabel(job.created_at)}</span> : null}
        <span>{job.pay ? job.pay : "Pay not stated"}</span>
        {job.location ? <span>{job.location}</span> : null}
      </p>
      <p className="mt-3 mb-0">
        <a href="/board" className="text-primary underline-offset-4 hover:underline">
          {job.id}
        </a>
      </p>
    </div>
  );
}

export function HomePage() {
  const [who, setWho] = useState<string | undefined>(undefined);
  const [conn, setConn] = useState<Conn>("signing in");
  const [dashboard, setDashboard] = useState<Dashboard | undefined>(undefined);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const me = await api<Whoami>("/api/whoami");
        if (cancelled) return;
        setWho(formatWho(me));
        setConn("signed in");
        const data = await api<Dashboard>("/api/dashboard");
        if (cancelled) return;
        setDashboard(data);
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "Could not load the dashboard";
        if (message.includes("unauthorized")) return;
        setConn("sign in required");
        setLoadError(message);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const max = dashboard ? funnelMax(dashboard.funnel) : 0;

  return (
    <AppShell
      title="jobOS Harness"
      subtitle="helps find jobs · live funnel · who is working"
      scroll="page"
      path="/home"
      who={who}
    >
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-5">
        <p className="m-0 flex items-center gap-2 text-sm text-muted-foreground">
          <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", connDotClass(conn))} />
          <span id="connLabel">{conn}</span>
        </p>

        <div className="grid gap-3 md:grid-cols-3">
          <Kpi
            label="Found today"
            valueId="kpiFoundToday"
            value={countText(dashboard?.today.found)}
            hint="Jobs POSTed to the board since 00:00 UTC"
          />
          <Kpi
            label="Applied today"
            valueId="kpiAppliedToday"
            value={countText(dashboard?.today.applied)}
            hint="Rows that reached applied"
          />
          <Kpi
            label="Oldest in pipeline"
            valueId="kpiOldestDays"
            value={oldestDays(dashboard)}
            hint={oldestHint(dashboard)}
            hintId="kpiOldestSub"
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(16rem,0.8fr)]">
          <section>
            <h2 className={sectionTitle}>Hunt funnel</h2>
            <div className="flex flex-col gap-3">
              {FUNNEL_STAGES.map((stage) => {
                const count = dashboard?.funnel[stage.key];
                const width = count === undefined ? "0%" : barWidth(count, max);
                return (
                  <Card key={stage.key} className="overflow-hidden p-0">
                    <div className="relative min-h-14">
                      <div
                        data-funnel={stage.label}
                        className="absolute inset-y-0 left-0 bg-primary/25"
                        style={{ width }}
                      />
                      <div className="relative flex items-baseline justify-between gap-3 px-4 py-3">
                        <span className="font-medium">{stage.label}</span>
                        <span className={`${display} text-[1.8rem] leading-none font-extrabold`}>
                          {countText(count)}
                        </span>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
            <ul id="funnelLegend" aria-live="polite" className="m-0 mt-3 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-sm text-muted-foreground">
              {FUNNEL_STAGES.map((stage) => (
                <li key={stage.key}>
                  {stage.label} <b className="text-foreground">{countText(dashboard?.funnel[stage.key])}</b>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2 className={sectionTitle}>Agents</h2>
            <Card className="p-4">
              <p id="agentWorking" className={valueClass}>
                {countText(dashboard?.agents.working)}
              </p>
              <p className="mt-2 mb-0 text-sm text-muted-foreground">working now</p>
              {dashboard ? (
                <p className="mt-1 mb-0 text-sm text-muted-foreground">
                  of {dashboard.agents.total} {dashboard.agents.total === 1 ? "agent" : "agents"} · {dashboard.agents.live} live
                </p>
              ) : null}
            </Card>
          </section>
        </div>

        <section>
          <h2 className={sectionTitle}>Oldest open job</h2>
          <Card className="p-4">
            <div id="oldestBody">
              {loadError ? (
                <p className="m-0 text-muted-foreground">{loadError}</p>
              ) : !dashboard ? (
                <p className="m-0 text-muted-foreground">Loading pipeline…</p>
              ) : !dashboard.oldest_in_pipeline ? (
                <p className="m-0 text-muted-foreground">Pipeline is empty. Discovery POSTs rows; then they age here.</p>
              ) : (
                <OldestBody job={dashboard.oldest_in_pipeline} />
              )}
            </div>
          </Card>
        </section>
      </main>
    </AppShell>
  );
}
