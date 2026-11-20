import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { api } from "@/lib/api";

const TABS = ["jobs", "people", "candidate", "skills", "mcps", "memory"] as const;
type Tab = (typeof TABS)[number];

type Row = Record<string, string>;

function isTab(value: string): value is Tab {
  return (TABS as readonly string[]).includes(value);
}

export function DataPage() {
  const [tab, setTab] = useState<Tab>("jobs");
  const [who, setWho] = useState("Checking session…");
  const [conn, setConn] = useState<ShellConn>("signing in");
  const [stats, setStats] = useState("");
  const [err, setErr] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [stopped, setStopped] = useState("");
  const [tag, setTag] = useState("");
  const [scope, setScope] = useState("");
  const [kind, setKind] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab") ?? "";
    if (isTab(requested)) setTab(requested);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<{ actor?: string; user?: { email?: string } }>("/api/auth/me")
      .then((me) => {
        if (!cancelled) {
          setWho(me.user?.email || me.actor || "signed in");
          setConn("signed in");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setWho("Sign in required.");
          setConn("sign in required");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setErr("");
      try {
        if (tab === "jobs") {
          const params = new URLSearchParams();
          if (q.trim()) params.set("q", q.trim());
          if (status.trim()) params.set("status", status.trim());
          if (stopped) params.set("stopped", stopped);
          const data = await api<{ jobs?: { id: string; company: string; title: string; status: string; score?: number | null }[]; count?: number; total?: number }>(
            `/api/jobs?${params.toString()}`,
          );
          if (cancelled) return;
          setStats(`${data.count || 0} shown · ${data.total || 0} total`);
          setHeaders(["ID", "Company", "Title", "Status", "Score"]);
          setRows(
            (data.jobs ?? []).map((job) => ({
              ID: job.id,
              Company: job.company,
              Title: job.title,
              Status: job.status,
              Score: job.score == null ? "" : String(job.score),
            })),
          );
          return;
        }
        if (tab === "people") {
          const params = new URLSearchParams();
          if (q.trim()) params.set("q", q.trim());
          const data = await api<{ people?: { id: string; name: string; company?: string; title?: string; job_id?: string }[]; count?: number }>(
            `/api/people?${params.toString()}`,
          );
          if (cancelled) return;
          setStats(`${data.count || 0} people`);
          setHeaders(["ID", "Name", "Company", "Title", "Job"]);
          setRows(
            (data.people ?? []).map((person) => ({
              ID: person.id,
              Name: person.name,
              Company: person.company || "",
              Title: person.title || "",
              Job: person.job_id || "",
            })),
          );
          return;
        }
        if (tab === "candidate") {
          const pub = await api<{ present?: boolean; revision?: string; source?: string; target?: { titles?: string[]; locations?: string[]; deal_breakers?: string[] }; work_authorization?: string; resume_url?: string }>("/api/candidate/public");
          const st = await api<{ onboarded?: boolean }>("/api/candidate/status");
          if (cancelled) return;
          setStats(`revision ${pub.revision || "none"} · onboarded ${String(st.onboarded)}`);
          setHeaders(["Field", "Value"]);
          setRows([
            { Field: "present", Value: String(pub.present) },
            { Field: "revision", Value: pub.revision || "" },
            { Field: "source", Value: pub.source || "" },
            { Field: "titles", Value: (pub.target?.titles ?? []).join(", ") },
            { Field: "locations", Value: (pub.target?.locations ?? []).join(", ") },
            { Field: "deal_breakers", Value: (pub.target?.deal_breakers ?? []).join(", ") },
            { Field: "work_authorization", Value: pub.work_authorization || "" },
            { Field: "resume", Value: pub.resume_url || "" },
          ]);
          return;
        }
        if (tab === "skills") {
          const params = new URLSearchParams();
          if (tag) params.set("tag", tag);
          if (scope) params.set("scope", scope);
          const data = await api<{ skills?: { slug: string; role: string; tags?: string[]; scope: string; status: string }[]; count?: number }>(
            `/api/registry/skills?${params.toString()}`,
          );
          if (cancelled) return;
          setStats(`${data.count || 0} skills`);
          setHeaders(["Slug", "Role", "Tags", "Scope", "Status"]);
          setRows(
            (data.skills ?? []).map((skill) => ({
              Slug: skill.slug,
              Role: skill.role,
              Tags: (skill.tags ?? []).join(", "),
              Scope: skill.scope,
              Status: skill.status,
            })),
          );
          return;
        }
        if (tab === "mcps") {
          const data = await api<{ connectors_needed?: { id: string; required?: boolean; hosted?: string; reason?: string }[]; mcp_example?: string }>(
            "/api/onboarding?track=discovery",
          );
          if (cancelled) return;
          const connectors = data.connectors_needed ?? [];
          setStats(`${connectors.length} connectors · example ${data.mcp_example || ""}`);
          setHeaders(["ID", "Required on discovery", "Hosted", "Reason"]);
          setRows(
            connectors.map((connector) => ({
              ID: connector.id,
              "Required on discovery": connector.required ? "required" : "optional",
              Hosted: connector.hosted || "",
              Reason: connector.reason || "",
            })),
          );
          return;
        }
        const params = new URLSearchParams();
        if (q.trim()) params.set("q", q.trim());
        if (kind.trim()) params.set("kind", kind.trim());
        const data = await api<{ items?: { id: string; pod?: string; kind?: string; title?: string; body?: string }[]; count?: number }>(
          `/api/memory/items?${params.toString()}`,
        );
        if (cancelled) return;
        setStats(`${data.count || data.items?.length || 0} facts`);
        setHeaders(["Pod", "Kind", "Title", "Fact"]);
        setRows(
          (data.items ?? []).map((item) => ({
            Pod: item.pod || "",
            Kind: item.kind || "",
            Title: item.title || "",
            Fact: item.body || "",
          })),
        );
      } catch (error) {
        if (cancelled) return;
        setErr(error instanceof Error ? error.message : "Could not load this tab");
        setRows([]);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [tab, q, status, stopped, tag, scope, kind, reloadKey]);

  return (
    <AppShell title="jobOS data" subtitle="Jobs, people, candidate, registry, memory — filter, do not dump." scroll="page" path="/admin/data" who={who} conn={conn}>
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5">
        <p id="who" className="m-0 text-sm text-muted-foreground">
          {who}
        </p>
        <div id="tabs" className="flex flex-wrap gap-2" role="tablist">
          {TABS.map((name) => (
            <Button
              key={name}
              type="button"
              variant={name === tab ? "default" : "outline"}
              data-tab={name}
              onClick={() => {
                if (isTab(name)) setTab(name);
              }}
            >
              {name}
            </Button>
          ))}
        </div>
        <div id="filters" className="flex flex-wrap items-center gap-2">
          {tab === "jobs" ? (
            <>
              <Input id="q" value={q} placeholder="Search company / title" onChange={(event) => setQ(event.target.value)} />
              <Input id="status" value={status} placeholder="status (apply_ready…)" onChange={(event) => setStatus(event.target.value)} />
              <NativeSelect
                id="stopped"
                label="Stopped"
                value={stopped}
                className="w-auto shrink-0"
                onChange={setStopped}
                options={[
                  { value: "", label: "Stopped: any" },
                  { value: "false", label: "active" },
                  { value: "true", label: "stopped" },
                ]}
              />
            </>
          ) : null}
          {tab === "people" || tab === "memory" ? (
            <Input id="q" value={q} placeholder={tab === "people" ? "Search name / company" : "Search facts"} onChange={(event) => setQ(event.target.value)} />
          ) : null}
          {tab === "memory" ? (
            <Input id="kind" value={kind} placeholder="kind" onChange={(event) => setKind(event.target.value)} />
          ) : null}
          {tab === "skills" ? (
            <>
              <NativeSelect
                id="tag"
                label="Tag"
                value={tag}
                className="w-auto shrink-0"
                onChange={setTag}
                options={[
                  { value: "", label: "all tags" },
                  { value: "source", label: "source" },
                  { value: "apply", label: "apply" },
                  { value: "outreach", label: "outreach" },
                ]}
              />
              <NativeSelect
                id="scope"
                label="Scope"
                value={scope}
                className="w-auto shrink-0"
                onChange={setScope}
                options={[
                  { value: "", label: "shared + mine" },
                  { value: "shared", label: "shared" },
                  { value: "local", label: "local" },
                ]}
              />
            </>
          ) : null}
          <Button id="go" type="button" onClick={() => setReloadKey((key) => key + 1)}>
            {tab === "memory" ? "Recall" : tab === "mcps" || tab === "candidate" ? "Refresh" : "Filter"}
          </Button>
        </div>
        <p id="stats" className="m-0 text-sm text-muted-foreground">
          {stats}
        </p>
        <p id="err" className="m-0 text-sm text-destructive">
          {err}
        </p>
        <div id="table" className="min-w-0 overflow-x-auto border border-border bg-card">
          {rows.length === 0 ? (
            <p className="m-0 p-4 text-sm text-muted-foreground">No rows match these filters.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  {headers.map((header) => (
                    <th key={header} className="px-3 py-2">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${tab}-${index}`} className="border-t border-border">
                    {headers.map((header) => (
                      <td key={header} className="px-3 py-2">
                        {row[header]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </AppShell>
  );
}
