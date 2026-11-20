import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { AppShell } from "@/components/shell/AppShell";
import type { ShellConn } from "@/components/shell/TopBar";
import { Badge } from "@/components/ui/badge";
import { Field } from "@/components/ui/field";
import { RecordCard, RecordDeck, RecordField } from "@/components/ui/record-card";
import { Table } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { NativeSelect } from "@/components/ui/select";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { panelVariants, usePageTransition, usePanelPlay, ticketMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";

type Who = {
  user?: { display_name?: string | null };
  display_name?: string | null;
  actor?: string | null;
  user_id?: string | null;
  kind?: string | null;
  role?: string | null;
  can_hygiene?: boolean;
  can_patch?: boolean;
  can_stop?: boolean;
  can_delete?: boolean;
  patch_fields?: string[];
};

type Job = {
  id: string;
  company?: string;
  title?: string;
  status?: string;
  stopped?: boolean;
  score?: number | null;
  pay?: string;
  posted_at?: string;
  created_at?: string;
  location?: string;
  apply_url?: string;
  description?: string;
  expectations?: string;
  notes?: string;
  sources?: string[];
  rejection?: { by?: string; company_remarks?: string; user_remarks?: string };
  owners?: unknown;
  apply_packet?: unknown;
  outreach_packet?: unknown;
  proof?: unknown;
  claim?: { claimed_by?: string; kind?: string; lease_until?: string };
};

type ListMeta = {
  count: number;
  total: number;
  matched: number;
  limit: number;
  offset: number;
  role: string;
};

type PresenceUser = {
  user_id?: string;
  display_name?: string;
  status?: string;
  kind?: string;
  track?: string;
  role?: string;
};

type MemoryItem = {
  pod_scope?: string;
  kind?: string;
  title?: string;
  body?: string;
};

type JobEvent = {
  ts?: string;
  actor_role?: string;
  action?: string;
  from_status?: string;
  to_status?: string;
  note?: string;
  job_id?: string;
};

type Packets = {
  owners: string;
  apply_packet: string;
  outreach_packet: string;
  proof: string;
};

const EMPTY_META: ListMeta = { count: 0, total: 0, matched: 0, limit: 25, offset: 0, role: "" };
const EMPTY_PACKETS: Packets = {
  owners: "{}",
  apply_packet: "{}",
  outreach_packet: "{}",
  proof: "{}",
};

function whoText(me: Who): string {
  const name = me.user?.display_name || me.display_name || me.actor || me.user_id || "admin";
  const lane = me.kind || me.role || "admin";
  return `${name} · ${lane}`;
}

function isAdmin(me: Who | null): boolean {
  return Boolean(me && (me.can_hygiene || me.kind === "owner" || me.role === "admin"));
}

function dayLabel(iso: string | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return date.toISOString().slice(0, 10);
}

function jsonText(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJSONField(raw: string, fallback: unknown): unknown {
  const text = raw.trim();
  if (!text) return fallback;
  return JSON.parse(text) as unknown;
}

function rootRem(): number {
  const size = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
  if (!Number.isFinite(size) || size <= 0) return 16;
  return size;
}

function Choice({
  id,
  label,
  value,
  placeholder,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  placeholder: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <NativeSelect
      id={id}
      label={label}
      value={value}
      className="w-auto min-w-[9rem] shrink-0"
      onChange={onChange}
      options={[{ value: "", label: placeholder }, ...options]}
    />
  );
}

export function BoardPage() {
  const reduce = useReducedMotion() === true;
  const play = usePanelPlay();
  const panel = panelVariants(reduce, play);
  const transition = usePageTransition();
  const stageRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const filtersRef = useRef<HTMLDivElement>(null);
  const [stageScrolls, setStageScrolls] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [pane, setPane] = useState<"jobs" | "presence">("jobs");
  const [conn, setConn] = useState<ShellConn>("signing in");
  const [who, setWho] = useState<string | undefined>(undefined);
  const [caps, setCaps] = useState<Who | null>(null);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [applyKinds, setApplyKinds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [meta, setMeta] = useState<ListMeta>(EMPTY_META);
  const [loaded, setLoaded] = useState(false);
  const [statsText, setStatsText] = useState("0 shown · 0 total · not connected");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [packets, setPackets] = useState<Packets>(EMPTY_PACKETS);
  const [sourceText, setSourceText] = useState("");
  const [sideErr, setSideErr] = useState("");
  const [presence, setPresence] = useState<PresenceUser[]>([]);
  const [presenceNote, setPresenceNote] = useState("Workers appear here when they take Hub actions. Click one to see what they are doing.");
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [memoryNote, setMemoryNote] = useState("Heartbeat recalls worker + track + common facts each round.");
  const [queueStats, setQueueStats] = useState("");
  const [q, setQ] = useState("");
  const [stopped, setStopped] = useState("");
  const [lane, setLane] = useState("");
  const [kind, setKind] = useState("");
  const [scoreMin, setScoreMin] = useState("");
  const [remote, setRemote] = useState("");
  const [pay, setPay] = useState("");
  const [location, setLocation] = useState("");
  const [source, setSource] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const openId = selected?.id ?? "";
  const queueVisible = isAdmin(caps);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 959px)");
    const apply = () => setNarrow(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("job")?.trim() ?? "";
    if (!id) return;
    void openJob(id).catch((error: unknown) => {
      setSideErr(error instanceof Error ? error.message : "Could not open job");
    });
  }, []);

  useLayoutEffect(() => {
    const measure = () => {
      const stage = stageRef.current;
      const toolbar = toolbarRef.current;
      const filters = filtersRef.current;
      if (!stage || !toolbar || !filters) return;
      const available = stage.parentElement?.clientHeight ?? stage.clientHeight;
      const pager = document.getElementById("pager");
      const queue = document.getElementById("queueRail");
      const queueHeight = queue && !queue.hidden ? queue.offsetHeight : 0;
      const fixed = toolbar.offsetHeight + filters.offsetHeight + (pager?.offsetHeight ?? 0) + queueHeight;
      const next = available - fixed < 8 * rootRem();
      setStageScrolls((prev) => (prev === next ? prev : next));
    };
    measure();
    const stage = stageRef.current;
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined" && stage) {
      observer = new ResizeObserver(measure);
      observer.observe(stage);
      if (stage.parentElement) observer.observe(stage.parentElement);
      if (toolbarRef.current) observer.observe(toolbarRef.current);
      if (filtersRef.current) observer.observe(filtersRef.current);
    }
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [queueVisible, filtersOpen]);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const me = await api<Who>("/api/whoami");
        if (cancelled) return;
        setCaps(me);
        setWho(whoText(me));
        setConn("signed in");
        const catalog = await api<{ statuses?: string[]; apply_kinds?: string[] }>("/api/meta");
        if (cancelled) return;
        setStatuses(catalog.statuses ?? []);
        setApplyKinds(catalog.apply_kinds ?? []);
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "";
        if (message.includes("unauthorized")) return;
        setConn("sign in required");
        if (message) setStatsText(message);
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!caps) return;
    let cancelled = false;
    async function loadJobs() {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (statusFilter) params.set("status", statusFilter);
      if (stopped) params.set("stopped", stopped);
      if (lane) params.set("lane", lane);
      if (kind) params.set("apply_kind", kind);
      if (scoreMin) params.set("score_min", scoreMin);
      if (remote) params.set("remote", remote);
      if (pay) params.set("has_pay", pay);
      if (location.trim()) params.set("location", location.trim());
      if (source.trim()) params.set("source", source.trim());
      params.set("limit", String(pageSize));
      params.set("offset", String(offset));
      const data = await api<{
        jobs?: Job[];
        count?: number;
        total?: number;
        matched?: number;
        limit?: number;
        offset?: number;
        role?: string;
      }>(`/api/jobs?${params.toString()}`);
      if (cancelled) return;
      const count = data.count ?? 0;
      const total = data.total ?? count;
      const matched = data.matched ?? count;
      const limit = data.limit || pageSize;
      const nextOffset = data.offset ?? offset;
      setJobs(data.jobs ?? []);
      setMeta({ count, total, matched, limit, offset: nextOffset, role: data.role ?? "" });
      setStatsText(`${count} shown · ${matched} match · ${total} total · ${data.role ?? ""}`);
      setLoaded(true);
    }
    void loadJobs().catch((error: unknown) => {
      if (cancelled) return;
      setLoaded(true);
      setStatsText(error instanceof Error ? error.message : "Could not load jobs");
    });
    return () => {
      cancelled = true;
    };
  }, [caps, q, statusFilter, stopped, lane, kind, scoreMin, remote, pay, location, source, pageSize, offset, reloadKey]);

  useEffect(() => {
    if (!caps) return;
    let cancelled = false;
    async function pulse() {
      const body = openId
        ? { status_hint: "working", task_id: openId, task_kind: "job", job_id: openId }
        : { status_hint: "logged_in" };
      try {
        const beat = await api<{ memory?: { items?: MemoryItem[]; hint?: string } }>("/api/presence/heartbeat", {
          method: "POST",
          body,
        });
        if (cancelled) return;
        const items = beat.memory?.items ?? [];
        setMemories(items);
        setMemoryNote(items.length ? "" : beat.memory?.hint || "No stored facts yet. Write only durable lessons.");
        const directory = await api<{ users?: PresenceUser[] }>("/api/presence");
        if (cancelled) return;
        const users = directory.users ?? [];
        setPresence(users);
        setPresenceNote(users.length ? "" : "No workers yet. They appear when they call the Hub.");
        if (isAdmin(caps)) {
          const queue = await api<{ items?: { kind?: string; status?: string }[] }>("/api/queue?limit=20");
          if (cancelled) return;
          const queued = queue.items ?? [];
          setQueueStats(queued.slice(0, 8).map((item) => `${item.kind}:${item.status}`).join(" · ") || "empty");
        }
      } catch {
        if (cancelled) return;
        setPresence([]);
        setPresenceNote("Directory is admin, maintenance, or track-owner only.");
      }
    }
    void pulse();
    const timer = window.setInterval(() => {
      void pulse();
    }, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [caps, openId]);

  function closeTicket() {
    setSelected(null);
    setEvents([]);
    setSideErr("");
  }

  async function openJob(id: string) {
    setSideErr("");
    const detail = await api<{ job: Job }>(`/api/jobs/${encodeURIComponent(id)}`);
    let nextEvents: JobEvent[] = [];
    try {
      const payload = await api<{ events?: JobEvent[] }>(`/api/events?job_id=${encodeURIComponent(id)}&limit=30`);
      nextEvents = payload.events ?? [];
    } catch {
      nextEvents = [];
    }
    const job = detail.job;
    setSourceText((job.sources ?? []).join(", "));
    setPackets({
      owners: jsonText(job.owners),
      apply_packet: jsonText(job.apply_packet),
      outreach_packet: jsonText(job.outreach_packet),
      proof: jsonText(job.proof),
    });
    setEvents(nextEvents);
    setSelected(job);
  }

  function updateJob(patch: Partial<Job>) {
    setSelected((current) => (current ? { ...current, ...patch } : current));
  }

  async function saveJob() {
    if (!selected) return;
    try {
      const body: Record<string, unknown> = {
        status: selected.status ?? "",
        company: selected.company ?? "",
        title: selected.title ?? "",
        apply_url: selected.apply_url ?? "",
        location: selected.location ?? "",
        notes: selected.notes ?? "",
        rejection: {
          by: selected.rejection?.by ?? "",
          company_remarks: selected.rejection?.company_remarks ?? "",
          user_remarks: selected.rejection?.user_remarks ?? "",
        },
        description: selected.description ?? "",
        expectations: selected.expectations ?? "",
        pay: selected.pay ?? "",
        posted_at: selected.posted_at ?? "",
        sources: sourceText.split(",").map((item) => item.trim()).filter(Boolean),
        owners: parseJSONField(packets.owners, {}),
        apply_packet: parseJSONField(packets.apply_packet, {}),
        outreach_packet: parseJSONField(packets.outreach_packet, {}),
        proof: parseJSONField(packets.proof, {}),
      };
      if (selected.score != null && String(selected.score) !== "") body.score = Number(selected.score);
      const allowed = new Set(caps?.patch_fields ?? []);
      for (const key of Object.keys(body)) {
        if (!allowed.has(key)) delete body[key];
      }
      await api(`/api/jobs/${encodeURIComponent(selected.id)}`, { method: "PATCH", body });
      setSideErr("Saved.");
      setReloadKey((key) => key + 1);
    } catch (error) {
      setSideErr(error instanceof Error ? error.message : "Could not save");
    }
  }

  async function pauseJob() {
    if (!selected) return;
    const reason = window.prompt("Pause reason (required). Status stays; lanes cannot patch until Resume.");
    if (!reason) return;
    try {
      await api(`/api/jobs/${encodeURIComponent(selected.id)}/pause`, { method: "POST", body: { reason } });
      setReloadKey((key) => key + 1);
    } catch (error) {
      setSideErr(error instanceof Error ? error.message : "Could not pause");
    }
  }

  async function stopJob() {
    if (!selected) return;
    const reason = window.prompt("Stop reason (required). Sets closed_withdrawn and freezes the row.");
    if (!reason) return;
    try {
      await api(`/api/jobs/${encodeURIComponent(selected.id)}/stop`, { method: "POST", body: { reason } });
      setReloadKey((key) => key + 1);
    } catch (error) {
      setSideErr(error instanceof Error ? error.message : "Could not stop");
    }
  }

  async function resumeJob() {
    if (!selected) return;
    try {
      await api(`/api/jobs/${encodeURIComponent(selected.id)}/resume`, { method: "POST" });
      setReloadKey((key) => key + 1);
    } catch (error) {
      setSideErr(error instanceof Error ? error.message : "Could not resume");
    }
  }

  async function deleteJob() {
    if (!selected) return;
    if (!window.confirm(`Delete ${selected.id}? This cannot be undone.`)) return;
    try {
      await api(`/api/jobs/${encodeURIComponent(selected.id)}`, { method: "DELETE" });
      closeTicket();
      setReloadKey((key) => key + 1);
    } catch (error) {
      setSideErr(error instanceof Error ? error.message : "Could not delete");
    }
  }

  const page = Math.floor(meta.offset / (meta.limit || 25)) + 1;
  const pages = Math.max(1, Math.ceil(meta.matched / (meta.limit || 25)));
  const statusOptions = selected?.status && !statuses.includes(selected.status) ? [...statuses, selected.status] : statuses;

  return (
    <AppShell
      title="jobOS Harness"
      subtitle="helps find jobs · workers run the tracks · you watch presence"
      scroll="panes"
      path="/board"
      who={who}
      conn={conn}
    >
      <a className="sr-only" href="/login?next=/board">
        Sign in
      </a>
      <div
        ref={stageRef}
        data-board-stage
        className={cn("flex min-h-0 min-w-0 flex-1 flex-col", stageScrolls ? "overflow-y-auto" : "overflow-hidden")}
      >
        <div ref={toolbarRef} data-board-toolbar className="shrink-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
            <div className="hidden items-center gap-1 rounded-full border border-primary p-0.5 max-[959px]:inline-flex" role="tablist" aria-label="Board pane">
              <Button type="button" data-board-pane="jobs" variant={pane === "jobs" ? "default" : "ghost"} className="rounded-full" aria-pressed={pane === "jobs"} onClick={() => setPane("jobs")}>
                Jobs
              </Button>
              <Button type="button" data-board-pane="presence" variant={pane === "presence" ? "default" : "ghost"} className="rounded-full" aria-pressed={pane === "presence"} onClick={() => setPane("presence")}>
                Live
              </Button>
            </div>
            <Input id="q" value={q} placeholder="Search company / title / not" className="min-w-40 flex-1" onChange={(event) => { setOffset(0); setQ(event.target.value); }} />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button id="statusBtn" type="button" variant="outline">
                  {statusFilter || "All statuses"}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onSelect={() => { setStatusFilter(""); setOffset(0); }}>All statuses</DropdownMenuItem>
                {statuses.map((status) => (
                  <DropdownMenuItem key={status} onSelect={() => { setStatusFilter(status); setOffset(0); }}>
                    {status}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <Choice
              id="stopped"
              label="Stopped"
              value={stopped}
              placeholder="Stopped: any"
              options={[
                { value: "false", label: "Stopped: active" },
                { value: "true", label: "Stopped: only" },
              ]}
              onChange={(value) => { setOffset(0); setStopped(value); }}
            />
            <Button id="refresh" type="button" variant="outline" onClick={() => setReloadKey((key) => key + 1)}>
              Refresh
            </Button>
            <Button
              type="button"
              variant={filtersOpen ? "default" : "outline"}
              className="min-[960px]:hidden"
              aria-expanded={filtersOpen}
              aria-controls="moreFilters"
              onClick={() => setFiltersOpen((open) => !open)}
            >
              Filters
            </Button>
            <span id="stats" className="text-sm text-muted-foreground">{statsText}</span>
          </div>
        </div>
        <div
          id="moreFilters"
          ref={filtersRef}
          className={cn(
            "shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2",
            filtersOpen ? "flex" : "hidden min-[960px]:flex",
          )}
        >
          <Choice id="laneFilter" label="Lane" value={lane} placeholder="Lane: any" onChange={(value) => { setOffset(0); setLane(value); }} options={[
            { value: "discovery", label: "Lane: discovery" },
            { value: "apply", label: "Lane: apply" },
            { value: "outreach", label: "Lane: outreach" },
          ]} />
          <Choice id="kindFilter" label="Apply kind" value={kind} placeholder="Kind: any" onChange={(value) => { setOffset(0); setKind(value); }} options={applyKinds.map((item) => ({ value: item, label: item }))} />
          <Choice id="scoreMin" label="Minimum score" value={scoreMin} placeholder="Score: any" onChange={(value) => { setOffset(0); setScoreMin(value); }} options={[
            { value: "3", label: "Score ≥ 3" },
            { value: "4", label: "Score ≥ 4" },
            { value: "5", label: "Score 5" },
          ]} />
          <Choice id="remoteFilter" label="Remote" value={remote} placeholder="Remote: any" onChange={(value) => { setOffset(0); setRemote(value); }} options={[
            { value: "remote", label: "Remote" },
            { value: "onsite", label: "On-site" },
          ]} />
          <Choice id="payFilter" label="Pay stated" value={pay} placeholder="Pay: any" onChange={(value) => { setOffset(0); setPay(value); }} options={[
            { value: "true", label: "Pay stated" },
            { value: "false", label: "Pay missing" },
          ]} />
          <Input id="locationFilter" value={location} placeholder="Location" aria-label="Location" className="w-44 shrink-0" onChange={(event) => { setOffset(0); setLocation(event.target.value); }} />
          <Input id="sourceFilter" value={source} placeholder="Source" aria-label="Source" className="w-44 shrink-0" onChange={(event) => { setOffset(0); setSource(event.target.value); }} />
        </div>
        <div id="queueRail" hidden={!queueVisible} className="flex shrink-0 gap-2 px-3 py-1 text-sm text-muted-foreground">
          <span>Queue</span>
          <span id="queueStats">{queueStats}</span>
        </div>
        <div id="main" className={cn("flex min-w-0 flex-1", stageScrolls ? "min-h-[8rem]" : "min-h-0")}>
          <motion.aside
            id="presenceRail"
            key={pane === "presence" ? "presence-on" : "presence-off"}
            initial={pane === "presence" ? panel.initial : false}
            animate={pane === "presence" ? panel.animate : { opacity: 1 }}
            transition={transition}
            className={cn(
              "w-56 shrink-0 overflow-y-auto border-r border-border p-3 max-[959px]:w-full max-[959px]:border-r-0",
              stageScrolls ? "min-h-[8rem]" : "min-h-0",
              pane === "jobs" && "max-[959px]:hidden",
            )}
          >
            <h2 className="mt-0 font-display text-[1.4rem] leading-none font-extrabold [font-family:var(--font-display)]">Presence</h2>
            <p id="presenceEmpty" hidden={presence.length > 0} className="text-sm text-muted-foreground">{presenceNote}</p>
            <div id="presenceList">
              {presence.map((user) => (
                <div key={user.user_id || user.display_name} className="py-1 text-sm">
                  <div className="font-medium">{user.display_name || user.user_id}</div>
                  <div className="text-muted-foreground">{user.status} · {user.kind || ""} · {user.track || user.role || ""}</div>
                </div>
              ))}
            </div>
            <h2 className="font-display text-[1.4rem] leading-none font-extrabold [font-family:var(--font-display)]">Memory</h2>
            <p id="memoryEmpty" hidden={memories.length > 0} className="text-sm text-muted-foreground">{memoryNote}</p>
            <div id="memoryList">
              {memories.map((item) => (
                <div key={`${item.pod_scope ?? ""}-${item.title ?? ""}`} className="py-1 text-sm">
                  <div className="text-muted-foreground">{item.pod_scope} · {item.kind}</div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-muted-foreground">{item.body}</div>
                </div>
              ))}
            </div>
          </motion.aside>
          <motion.section
            id="list"
            key={pane === "jobs" ? "jobs-on" : "jobs-off"}
            initial={pane === "jobs" ? panel.initial : false}
            animate={pane === "jobs" ? panel.animate : { opacity: 1 }}
            transition={transition}
            className={cn(
              "min-w-0 flex-1 overflow-y-auto",
              stageScrolls ? "min-h-[8rem]" : "min-h-0",
              pane === "presence" && "max-[959px]:hidden",
            )}
          >
            {!loaded ? (
              <p className="p-4 text-sm text-muted-foreground">Loading jobs…</p>
            ) : jobs.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No jobs on this page.</p>
            ) : (
              <>
              <RecordDeck>
                {jobs.map((job) => (
                  <RecordCard
                    key={job.id}
                    title={job.company || "Job"}
                    subtitle={job.title || ""}
                    onClick={() => void openJob(job.id)}
                  >
                    <RecordField label="Status" value={job.stopped ? "stopped" : job.status || ""} />
                    <RecordField label="Score" value={job.score == null ? "" : String(job.score)} />
                    <RecordField label="Pay" value={job.pay || "—"} />
                    <RecordField label="Posted" value={dayLabel(job.posted_at) || dayLabel(job.created_at)} />
                    <RecordField label="Claim" value={job.claim?.claimed_by || job.claim?.kind || ""} />
                  </RecordCard>
                ))}
              </RecordDeck>
              <Table className="max-[720px]:hidden">
                <thead className="sticky top-0 z-10 bg-card">
                  <tr>
                    <th className="w-[20%] px-3 py-2 max-[959px]:w-[38%]">Company</th>
                    <th className="w-[26%] px-3 py-2 max-[959px]:w-[40%]">Title</th>
                    <th className="w-[14%] px-3 py-2 max-[959px]:w-[22%]">Status</th>
                    <th className="w-[8%] px-3 py-2 max-[959px]:hidden">Score</th>
                    <th className="w-[8%] px-3 py-2 max-[959px]:hidden">Pay</th>
                    <th className="w-[16%] px-3 py-2 max-[959px]:hidden">Posted</th>
                    <th className="w-[8%] px-3 py-2 max-[959px]:hidden">Claim</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id} data-id={job.id} className="cursor-pointer border-t border-border" onClick={() => void openJob(job.id)}>
                      <td className="truncate px-3 py-2" title={job.company}>{job.company}</td>
                      <td className="break-words px-3 py-2" title={job.title}>{job.title}</td>
                      <td className="px-3 py-2">
                        <Badge variant="outline" className="max-w-full truncate border-dashed border-current">
                          {job.stopped ? "stopped" : job.status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 max-[959px]:hidden">{job.score ?? ""}</td>
                      <td className="truncate px-3 py-2 max-[959px]:hidden" title={job.pay || ""}>{job.pay || "—"}</td>
                      <td className="truncate px-3 py-2 max-[959px]:hidden">{dayLabel(job.posted_at) || dayLabel(job.created_at)}</td>
                      <td className="truncate px-3 py-2 max-[959px]:hidden">{job.claim?.claimed_by || job.claim?.kind || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              </>
            )}
          </motion.section>
          <TicketFrame
            narrow={narrow}
            open={selected !== null}
            onClose={closeTicket}
            footer={selected ? (
              <div className="shrink-0 border-t border-border bg-card p-3">
                <div className="flex flex-wrap gap-2">
                  <Button id="saveBtn" type="button" disabled={!caps?.can_patch} onClick={() => void saveJob()}>Save patch</Button>
                  <Button id="pauseBtn" type="button" variant="outline" disabled={!caps?.can_stop || Boolean(selected.stopped)} onClick={() => void pauseJob()}>Pause</Button>
                  <Button id="stopBtn" type="button" variant="outline" disabled={!caps?.can_stop || Boolean(selected.stopped)} onClick={() => void stopJob()}>Stop</Button>
                  <Button id="resumeBtn" type="button" variant="secondary" disabled={!caps?.can_stop || !selected.stopped} onClick={() => void resumeJob()}>Resume</Button>
                  <Button id="delBtn" type="button" variant="destructive" disabled={!caps?.can_delete} onClick={() => void deleteJob()}>Delete</Button>
                </div>
                <p id="sideErr" className="mt-2 text-sm">{sideErr}</p>
              </div>
            ) : null}
          >
            {selected ? (
              <motion.div
                key={selected.id}
                initial={ticketMotion(narrow, panel).initial}
                animate={ticketMotion(narrow, panel).animate}
                transition={transition}
                className="flex flex-col gap-1 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <h2 className="m-0 truncate font-display text-lg leading-tight font-extrabold [font-family:var(--font-display)]" title={selected.company}>
                      {selected.company || "Job"}
                    </h2>
                    <p className="m-0 truncate font-mono text-xs text-muted-foreground" title={selected.id}>
                      {selected.id}
                    </p>
                  </div>
                  <Button id="closeSide" type="button" variant="outline" aria-label="Close" onClick={closeTicket}>
                    Close
                  </Button>
                </div>
                {selected.claim ? (
                  <p className="m-0 text-sm">
                    Claimed: {selected.claim.kind} by {selected.claim.claimed_by || ""} until {selected.claim.lease_until || ""}
                  </p>
                ) : null}
                <Field htmlFor="f_company">Company<Input id="f_company" value={selected.company ?? ""} onChange={(event) => updateJob({ company: event.target.value })} /></Field>
                <Field htmlFor="f_title">Title<Input id="f_title" value={selected.title ?? ""} onChange={(event) => updateJob({ title: event.target.value })} /></Field>
                <Field htmlFor="f_status">
                  Status
                  <NativeSelect
                    id="f_status"
                    label="Status"
                    value={selected.status || ""}
                    options={statusOptions.map((status) => ({ value: status, label: status }))}
                    onChange={(value) => updateJob({ status: value })}
                  />
                </Field>
                <Field htmlFor="f_source">Source<Input id="f_source" value={sourceText} onChange={(event) => setSourceText(event.target.value)} /></Field>
                <Field htmlFor="f_score">Score<Input id="f_score" type="number" min={1} max={5} step={1} value={selected.score == null ? "" : String(selected.score)} onChange={(event) => updateJob({ score: event.target.value === "" ? null : Number(event.target.value) })} /></Field>
                <Field htmlFor="f_location">Location<Input id="f_location" value={selected.location ?? ""} onChange={(event) => updateJob({ location: event.target.value })} /></Field>
                <Field htmlFor="f_apply_url">Apply URL<Input id="f_apply_url" value={selected.apply_url ?? ""} onChange={(event) => updateJob({ apply_url: event.target.value })} /></Field>
                <Field htmlFor="f_posted_at">Posted<Input id="f_posted_at" value={selected.posted_at ?? ""} placeholder="2026-09-01T00:00:00Z" onChange={(event) => updateJob({ posted_at: event.target.value })} /></Field>
                <Field htmlFor="f_pay">Pay<Input id="f_pay" value={selected.pay ?? ""} placeholder="as the posting states it" onChange={(event) => updateJob({ pay: event.target.value })} /></Field>
                <Field htmlFor="f_description">Job description<Textarea id="f_description" value={selected.description ?? ""} onChange={(event) => updateJob({ description: event.target.value })} /></Field>
                <Field htmlFor="f_expectations">Expectations<Textarea id="f_expectations" value={selected.expectations ?? ""} onChange={(event) => updateJob({ expectations: event.target.value })} /></Field>
                <Field htmlFor="f_notes">Notes<Textarea id="f_notes" value={selected.notes ?? ""} onChange={(event) => updateJob({ notes: event.target.value })} /></Field>
                <Field htmlFor="f_rejection_by">
                  Rejected by
                  <NativeSelect
                    id="f_rejection_by"
                    label="Rejected by"
                    value={selected.rejection?.by || "none"}
                    options={[
                      { value: "none", label: "—" },
                      { value: "company", label: "company" },
                      { value: "user", label: "user" },
                    ]}
                    onChange={(value) => updateJob({ rejection: { ...selected.rejection, by: value === "none" ? "" : value } })}
                  />
                </Field>
                <Field htmlFor="f_company_remarks">Company remarks<Textarea id="f_company_remarks" value={selected.rejection?.company_remarks ?? ""} onChange={(event) => updateJob({ rejection: { ...selected.rejection, company_remarks: event.target.value } })} /></Field>
                <Field htmlFor="f_user_remarks">User remarks<Textarea id="f_user_remarks" value={selected.rejection?.user_remarks ?? ""} onChange={(event) => updateJob({ rejection: { ...selected.rejection, user_remarks: event.target.value } })} /></Field>
                <Field htmlFor="f_owners">Owners JSON<Textarea id="f_owners" value={packets.owners} onChange={(event) => setPackets((current) => ({ ...current, owners: event.target.value }))} /></Field>
                <Field htmlFor="f_apply_packet">Apply packet JSON<Textarea id="f_apply_packet" value={packets.apply_packet} onChange={(event) => setPackets((current) => ({ ...current, apply_packet: event.target.value }))} /></Field>
                <Field htmlFor="f_outreach_packet">Outreach packet JSON<Textarea id="f_outreach_packet" value={packets.outreach_packet} onChange={(event) => setPackets((current) => ({ ...current, outreach_packet: event.target.value }))} /></Field>
                <Field htmlFor="f_proof">Proof JSON<Textarea id="f_proof" value={packets.proof} onChange={(event) => setPackets((current) => ({ ...current, proof: event.target.value }))} /></Field>
                <div>
                  <h2 className="font-display text-[1.2rem] leading-none font-extrabold [font-family:var(--font-display)]">Events</h2>
                  {events.length === 0 ? <p className="text-sm text-muted-foreground">No events</p> : events.map((event) => (
                    <p key={`${event.ts ?? ""}-${event.action ?? ""}`} className="text-sm">
                      {event.ts} · {event.actor_role} · {event.action}
                      {event.from_status ? ` · ${event.from_status} → ${event.to_status || ""}` : ""}
                      {event.note ? ` ${event.note}` : ""}
                    </p>
                  ))}
                </div>
              </motion.div>
            ) : (
              <div hidden>
                <label htmlFor="f_rejection_by">Rejected by</label>
                <input id="f_rejection_by" defaultValue="" />
                <textarea id="f_company_remarks" defaultValue="" />
                <textarea id="f_user_remarks" defaultValue="" />
              </div>
            )}
          </TicketFrame>
        </div>
        <div id="pager" className="flex shrink-0 items-center justify-between gap-2 border-t border-border px-3 py-2">
          <span id="pageLabel" className="text-sm text-muted-foreground">
            {loaded ? `Page ${page} of ${pages}` : "Page 1"}
          </span>
          <div className="flex items-center gap-2">
            <Button id="prevPage" type="button" variant="outline" disabled={meta.offset <= 0} onClick={() => setOffset((value) => Math.max(0, value - (meta.limit || pageSize)))}>
              Prev
            </Button>
            <NativeSelect
              id="pageSize"
              label="Page size"
              value={String(pageSize)}
              className="w-auto shrink-0"
              onChange={(value) => { setOffset(0); setPageSize(Number(value) || 25); }}
              options={[
                { value: "25", label: "25 / page" },
                { value: "50", label: "50 / page" },
                { value: "100", label: "100 / page" },
              ]}
            />
            <Button id="nextPage" type="button" variant="outline" disabled={meta.offset + meta.count >= meta.matched} onClick={() => setOffset((value) => value + (meta.limit || pageSize))}>
              Next
            </Button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function TicketFrame({
  narrow,
  open,
  onClose,
  footer,
  children,
}: {
  narrow: boolean;
  open: boolean;
  onClose: () => void;
  footer?: ReactNode;
  children: ReactNode;
}) {
  if (!narrow) {
    return (
      <aside id="side" hidden={!open} className="flex min-h-0 w-80 min-w-0 max-w-80 shrink-0 flex-col overflow-hidden border-l border-border">
        {open ? <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea> : children}
        {open ? footer : null}
      </aside>
    );
  }
  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent id="side" side="bottom" className="flex h-[92dvh] max-h-[92dvh] flex-col gap-0 overflow-hidden rounded-t-[var(--radius-sheet)] px-4 pt-14 pb-[calc(1rem+env(safe-area-inset-bottom))]">
        <SheetTitle className="sr-only">Job ticket</SheetTitle>
        <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea>
        {footer}
      </SheetContent>
    </Sheet>
  );
}
