import { useEffect, useRef, useState, type ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import type { ShellConn } from "@/components/shell/TopBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

const selectClass =
  "flex min-h-[2.75rem] rounded-md border border-input bg-background px-3 text-sm text-foreground";

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
  claim?: { claimed_by?: string; kind?: string };
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
};

const EMPTY_META: ListMeta = { count: 0, total: 0, matched: 0, limit: 25, offset: 0, role: "" };

function whoText(me: Who): string {
  const name = me.user?.display_name || me.display_name || me.actor || me.user_id || "";
  const lane = me.kind || me.role || "";
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

export function BoardPage() {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLElement>(null);
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
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<Job | null>(null);
  const [sideErr, setSideErr] = useState("");
  const [presence, setPresence] = useState<PresenceUser[]>([]);
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
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 959px)");
    const apply = () => setNarrow(media.matches);
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const stage = stageRef.current;
    const toolbar = toolbarRef.current;
    if (!stage || !toolbar || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const room = stage.clientHeight - toolbar.offsetHeight - 48;
      setStageScrolls(room < 128);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    observer.observe(toolbar);
    return () => observer.disconnect();
  }, []);

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
      const data = await api<{ jobs?: Job[]; count?: number; total?: number; matched?: number; limit?: number; offset?: number; role?: string }>(
        `/api/jobs?${params.toString()}`,
      );
      if (cancelled) return;
      setJobs(data.jobs ?? []);
      setMeta({
        count: data.count ?? 0,
        total: data.total ?? data.count ?? 0,
        matched: data.matched ?? data.count ?? 0,
        limit: data.limit || pageSize,
        offset: data.offset ?? offset,
        role: data.role ?? "",
      });
      setLoaded(true);
    }
    void loadJobs().catch((error: unknown) => {
      if (!cancelled) setSideErr(error instanceof Error ? error.message : "Could not load jobs");
    });
    return () => {
      cancelled = true;
    };
  }, [caps, q, statusFilter, stopped, lane, kind, scoreMin, remote, pay, location, source, pageSize, offset, reloadKey]);

  useEffect(() => {
    if (!caps) return;
    let cancelled = false;
    async function beat() {
      const body = selected
        ? { status_hint: "working", task_id: selected.id, task_kind: "job", job_id: selected.id }
        : { status_hint: "logged_in" };
      await api("/api/presence/heartbeat", { method: "POST", body });
      const data = await api<{ users?: PresenceUser[] }>("/api/presence");
      if (!cancelled) setPresence(data.users ?? []);
      if (isAdmin(caps)) {
        const queue = await api<{ items?: { kind?: string; status?: string }[] }>("/api/queue?limit=20");
        if (!cancelled) {
          const items = queue.items ?? [];
          setQueueStats(items.slice(0, 8).map((item) => `${item.kind}:${item.status}`).join(" · ") || "empty");
        }
      }
    }
    void beat().catch(() => undefined);
    const timer = window.setInterval(() => {
      void beat().catch(() => undefined);
    }, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [caps, selected]);

  async function openJob(id: string) {
    setSideErr("");
    const detail = await api<{ job: Job }>(`/api/jobs/${encodeURIComponent(id)}`);
    setSelected(detail.job);
  }

  function updateJob(patch: Partial<Job>) {
    setSelected((current) => (current ? { ...current, ...patch } : current));
  }

  async function saveJob() {
    if (!selected) return;
    setSideErr("");
    const score = selected.score;
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
      sources: (selected.sources ?? []).map((item) => item.trim()).filter(Boolean),
      owners: selected.owners ?? {},
      apply_packet: selected.apply_packet ?? {},
      outreach_packet: selected.outreach_packet ?? {},
      proof: selected.proof ?? {},
    };
    if (score != null && String(score) !== "") body.score = Number(score);
    const allowed = new Set(caps?.patch_fields ?? []);
    for (const key of Object.keys(body)) {
      if (!allowed.has(key)) delete body[key];
    }
    try {
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
      setSelected(null);
      setReloadKey((key) => key + 1);
    } catch (error) {
      setSideErr(error instanceof Error ? error.message : "Could not delete");
    }
  }

  const page = Math.floor(meta.offset / (meta.limit || 25)) + 1;
  const pages = Math.max(1, Math.ceil(meta.matched / (meta.limit || 25)));
  const showPresence = !narrow || pane === "presence";
  const showJobs = !narrow || pane === "jobs";

  return (
    <AppShell
      title="jobOS Harness"
      subtitle="helps find jobs · workers run the tracks · you watch presence"
      scroll="panes"
      path="/board"
      who={who}
      conn={conn}
    >
      <main
        id="main"
        ref={stageRef}
        className={stageScrolls ? "flex min-h-0 flex-1 flex-col overflow-y-auto" : "flex min-h-0 flex-1 flex-col overflow-hidden"}
      >
        <div ref={toolbarRef} className="shrink-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
            <div className="flex rounded-full border border-primary p-0.5 min-[960px]:hidden" role="tablist" aria-label="Board pane">
              <button type="button" data-board-pane="jobs" className="min-h-[2.75rem] rounded-full px-3" onClick={() => setPane("jobs")}>
                Jobs
              </button>
              <button type="button" data-board-pane="presence" className="min-h-[2.75rem] rounded-full px-3" onClick={() => setPane("presence")}>
                Live
              </button>
            </div>
            <Input id="q" value={q} placeholder="Search company / title / not" className="min-w-40 flex-1" onChange={(event) => { setOffset(0); setQ(event.target.value); }} />
            <DropdownMenu>
              <DropdownMenuTrigger id="statusBtn" className="rounded-md border border-border bg-background px-3">
                {statusFilter || "All statuses"}
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
            <select id="stopped" className={selectClass} aria-label="Stopped" value={stopped} onChange={(event) => { setOffset(0); setStopped(event.target.value); }}>
              <option value="">Stopped: any</option>
              <option value="false">Stopped: active</option>
              <option value="true">Stopped: only</option>
            </select>
            <Button id="refresh" type="button" variant="outline" onClick={() => setReloadKey((key) => key + 1)}>
              Refresh
            </Button>
            <span id="stats" className="text-sm text-muted-foreground">
              {loaded ? `${meta.count} shown · ${meta.matched} match · ${meta.total} total · ${meta.role}` : "0 shown · 0 total · not connected"}
            </span>
          </div>
          <div id="moreFilters" className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
            <select id="laneFilter" className={selectClass} aria-label="Lane" value={lane} onChange={(event) => { setOffset(0); setLane(event.target.value); }}>
              <option value="">Lane: any</option>
              <option value="discovery">Lane: discovery</option>
              <option value="apply">Lane: apply</option>
              <option value="outreach">Lane: outreach</option>
            </select>
            <select id="kindFilter" className={selectClass} aria-label="Apply kind" value={kind} onChange={(event) => { setOffset(0); setKind(event.target.value); }}>
              <option value="">Kind: any</option>
              {applyKinds.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
            <select id="scoreMin" className={selectClass} aria-label="Minimum score" value={scoreMin} onChange={(event) => { setOffset(0); setScoreMin(event.target.value); }}>
              <option value="">Score: any</option>
              <option value="3">Score ≥ 3</option>
              <option value="4">Score ≥ 4</option>
              <option value="5">Score 5</option>
            </select>
            <select id="remoteFilter" className={selectClass} aria-label="Remote" value={remote} onChange={(event) => { setOffset(0); setRemote(event.target.value); }}>
              <option value="">Remote: any</option>
              <option value="remote">Remote</option>
              <option value="onsite">On-site</option>
            </select>
            <select id="payFilter" className={selectClass} aria-label="Pay stated" value={pay} onChange={(event) => { setOffset(0); setPay(event.target.value); }}>
              <option value="">Pay: any</option>
              <option value="true">Pay stated</option>
              <option value="false">Pay missing</option>
            </select>
            <Input id="locationFilter" value={location} placeholder="Location" onChange={(event) => { setOffset(0); setLocation(event.target.value); }} />
            <Input id="sourceFilter" value={source} placeholder="Source" onChange={(event) => { setOffset(0); setSource(event.target.value); }} />
          </div>
          {isAdmin(caps) ? (
            <div className="flex gap-2 px-3 py-1 text-sm text-muted-foreground">
              <span>Queue</span>
              <span id="queueStats">{queueStats}</span>
            </div>
          ) : (
            <span id="queueStats" className="hidden" />
          )}
        </div>
        <div className="flex min-h-0 min-w-0 flex-1">
          <aside id="presenceRail" className={showPresence ? "w-56 shrink-0 overflow-y-auto border-r border-border p-3" : "hidden"}>
            <h2 className="mt-0 font-display text-[1.4rem] leading-none font-extrabold [font-family:var(--font-display)]">Presence</h2>
            {presence.length === 0 ? (
              <p id="presenceEmpty" className="text-sm text-muted-foreground">Workers appear here when they take Hub actions.</p>
            ) : (
              <ul id="presenceList" className="m-0 list-none p-0">
                {presence.map((user) => (
                  <li key={user.user_id || user.display_name} className="py-1 text-sm">
                    {user.display_name || user.user_id} · {user.status}
                  </li>
                ))}
              </ul>
            )}
          </aside>
          <section id="list" className={showJobs ? "min-h-0 min-w-0 flex-1 overflow-y-auto" : "hidden"}>
            {!loaded ? (
              <p className="p-4 text-sm text-muted-foreground">Loading jobs…</p>
            ) : jobs.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">No jobs on this page.</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr>
                    <th className="px-3 py-2">Company</th>
                    <th className="px-3 py-2">Title</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Score</th>
                    <th className="px-3 py-2">Pay</th>
                    <th className="px-3 py-2">Posted</th>
                    <th className="px-3 py-2">Claim</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id} data-id={job.id} className="cursor-pointer border-t border-border" onClick={() => void openJob(job.id)}>
                      <td className="px-3 py-2">{job.company}</td>
                      <td className="px-3 py-2">{job.title}</td>
                      <td className="px-3 py-2">
                        <Badge variant="outline" className="border-dashed border-current">
                          {job.stopped ? "stopped" : job.status}
                        </Badge>
                      </td>
                      <td className="px-3 py-2">{job.score ?? ""}</td>
                      <td className="px-3 py-2">{job.pay || "—"}</td>
                      <td className="px-3 py-2">{dayLabel(job.posted_at) || dayLabel(job.created_at)}</td>
                      <td className="px-3 py-2">{job.claim?.claimed_by || job.claim?.kind || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          {selected ? (
            <TicketFrame narrow={narrow} onClose={() => setSelected(null)}>
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="m-0 font-display text-[1.4rem] leading-none font-extrabold [font-family:var(--font-display)]">{selected.company}</h2>
                <Button id="closeSide" type="button" variant="outline" onClick={() => setSelected(null)}>
                  Close
                </Button>
              </div>
              <div className="flex flex-col gap-2">
                <label className="text-sm">Company<Input id="f_company" value={selected.company ?? ""} onChange={(event) => updateJob({ company: event.target.value })} /></label>
                <label className="text-sm">Title<Input id="f_title" value={selected.title ?? ""} onChange={(event) => updateJob({ title: event.target.value })} /></label>
                <label className="text-sm">Source<Input id="f_source" value={(selected.sources ?? []).join(", ")} onChange={(event) => updateJob({ sources: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label>
                <label className="text-sm">Status<Input id="f_status" value={selected.status ?? ""} onChange={(event) => updateJob({ status: event.target.value })} /></label>
                <label className="text-sm">Score<Input id="f_score" value={selected.score == null ? "" : String(selected.score)} onChange={(event) => updateJob({ score: event.target.value === "" ? null : Number(event.target.value) })} /></label>
                <label className="text-sm">Location<Input id="f_location" value={selected.location ?? ""} onChange={(event) => updateJob({ location: event.target.value })} /></label>
                <label className="text-sm">Apply URL<Input id="f_apply_url" value={selected.apply_url ?? ""} onChange={(event) => updateJob({ apply_url: event.target.value })} /></label>
                <label className="text-sm">Posted<Input id="f_posted_at" value={selected.posted_at ?? ""} onChange={(event) => updateJob({ posted_at: event.target.value })} /></label>
                <label className="text-sm">Pay<Input id="f_pay" value={selected.pay ?? ""} onChange={(event) => updateJob({ pay: event.target.value })} /></label>
                <label className="text-sm">Description<Textarea id="f_description" value={selected.description ?? ""} onChange={(event) => updateJob({ description: event.target.value })} /></label>
                <label className="text-sm">Expectations<Textarea id="f_expectations" value={selected.expectations ?? ""} onChange={(event) => updateJob({ expectations: event.target.value })} /></label>
                <label className="text-sm">Notes<Textarea id="f_notes" value={selected.notes ?? ""} onChange={(event) => updateJob({ notes: event.target.value })} /></label>
                <label className="text-sm">Rejected by<Input id="f_rejection_by" value={selected.rejection?.by ?? ""} onChange={(event) => updateJob({ rejection: { ...selected.rejection, by: event.target.value } })} /></label>
                <label className="text-sm">Company remarks<Textarea id="f_company_remarks" value={selected.rejection?.company_remarks ?? ""} onChange={(event) => updateJob({ rejection: { ...selected.rejection, company_remarks: event.target.value } })} /></label>
                <label className="text-sm">User remarks<Textarea id="f_user_remarks" value={selected.rejection?.user_remarks ?? ""} onChange={(event) => updateJob({ rejection: { ...selected.rejection, user_remarks: event.target.value } })} /></label>
                <label className="text-sm">Owners JSON<Textarea id="f_owners" value={jsonText(selected.owners)} onChange={(event) => updateJob({ owners: parseJson(event.target.value, {}) })} /></label>
                <label className="text-sm">Apply packet JSON<Textarea id="f_apply_packet" value={jsonText(selected.apply_packet)} onChange={(event) => updateJob({ apply_packet: parseJson(event.target.value, {}) })} /></label>
                <label className="text-sm">Outreach packet JSON<Textarea id="f_outreach_packet" value={jsonText(selected.outreach_packet)} onChange={(event) => updateJob({ outreach_packet: parseJson(event.target.value, {}) })} /></label>
                <label className="text-sm">Proof JSON<Textarea id="f_proof" value={jsonText(selected.proof)} onChange={(event) => updateJob({ proof: parseJson(event.target.value, {}) })} /></label>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button id="saveBtn" type="button" disabled={!caps?.can_patch} onClick={() => void saveJob()}>Save patch</Button>
                <Button id="pauseBtn" type="button" variant="outline" disabled={!caps?.can_stop || selected.stopped} onClick={() => void pauseJob()}>Pause</Button>
                <Button id="stopBtn" type="button" variant="outline" disabled={!caps?.can_stop || selected.stopped} onClick={() => void stopJob()}>Stop</Button>
                <Button id="resumeBtn" type="button" variant="outline" disabled={!caps?.can_stop || !selected.stopped} onClick={() => void resumeJob()}>Resume</Button>
                <Button id="delBtn" type="button" variant="destructive" disabled={!caps?.can_delete} onClick={() => void deleteJob()}>Delete</Button>
              </div>
              <p id="sideErr" className="text-sm">{sideErr}</p>
            </TicketFrame>
          ) : null}
        </div>
        <div id="pager" className="flex shrink-0 items-center justify-between gap-2 border-t border-border px-3 py-2">
          <span id="pageLabel" className="text-sm text-muted-foreground">Page {loaded ? page : 1} of {loaded ? pages : 1}</span>
          <div className="flex items-center gap-2">
            <Button id="prevPage" type="button" variant="outline" disabled={meta.offset <= 0} onClick={() => setOffset((value) => Math.max(0, value - pageSize))}>Prev</Button>
            <select id="pageSize" className={selectClass} aria-label="Page size" value={String(pageSize)} onChange={(event) => { setOffset(0); setPageSize(Number(event.target.value) || 25); }}>
              <option value="25">25 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
            <Button id="nextPage" type="button" variant="outline" disabled={meta.offset + meta.count >= meta.matched} onClick={() => setOffset((value) => value + pageSize)}>Next</Button>
          </div>
        </div>
      </main>
    </AppShell>
  );
}

function TicketFrame({
  narrow,
  onClose,
  children,
}: {
  narrow: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!narrow) {
    return <aside id="side" className="w-80 shrink-0 overflow-y-auto border-l border-border p-3">{children}</aside>;
  }
  return (
    <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent id="side" side="bottom" className="max-h-[85dvh] overflow-y-auto rounded-t-[12px]">
        {children}
      </SheetContent>
    </Sheet>
  );
}

function parseJson(raw: string, fallback: unknown): unknown {
  const text = raw.trim();
  if (!text) return fallback;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return fallback;
  }
}
