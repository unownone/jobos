import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

const selectClass =
  "flex min-h-[2.75rem] w-full rounded-md border border-input bg-background px-3 text-sm text-foreground";

type Pod = { id: string; label: string; writable?: boolean };
type Item = {
  id: string;
  pod?: string;
  kind?: string;
  title?: string;
  body?: string;
  pod_scope?: string;
  solidify_status?: string;
  recording_id?: string;
};

function scopeOf(podId: string): string {
  if (!podId || podId === "worker" || podId.startsWith("worker:")) return "worker";
  if (podId === "common" || podId.startsWith("common")) return "common";
  return "track";
}

export function MemoryPage() {
  const [who, setWho] = useState("");
  const [pods, setPods] = useState<Pod[]>([]);
  const [kinds, setKinds] = useState<Record<string, string[]>>({});
  const [policy, setPolicy] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [status, setStatus] = useState("");
  const [err, setErr] = useState("");
  const [writePod, setWritePod] = useState("");
  const [writeKind, setWriteKind] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [company, setCompany] = useState("");
  const [filterPod, setFilterPod] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [query, setQuery] = useState("");
  const [sharePod, setSharePod] = useState("");
  const [shareKind, setShareKind] = useState("");

  const writeKinds = kinds[scopeOf(writePod)] ?? [];

  async function loadItems(pod = filterPod, q = query, kind = filterKind) {
    const params = new URLSearchParams();
    if (pod) params.set("pod", pod);
    if (q.trim()) params.set("q", q.trim());
    if (kind.trim()) params.set("kind", kind.trim());
    const data = await api<{ items?: Item[] }>(`/api/memory/items?${params.toString()}`);
    setItems(data.items ?? []);
  }

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const me = await api<{ user?: { display_name?: string }; actor?: string; user_id?: string; track?: string; role?: string }>("/api/auth/me");
        if (cancelled) return;
        const name = me.user?.display_name || me.actor || me.user_id || "signed in";
        setWho(`${name} · ${me.track || me.role || ""}`);
        const podData = await api<{ pods?: Pod[]; kinds?: Record<string, string[]>; write_policy?: { store_when?: string; caps?: Record<string, number> } }>(
          "/api/memory/pods",
        );
        if (cancelled) return;
        const list = podData.pods ?? [];
        setPods(list);
        setKinds(podData.kinds ?? {});
        const writable = list.filter((pod) => pod.writable !== false);
        const first = writable[0]?.id ?? "";
        setWritePod(first);
        setSharePod(first);
        const policyText = podData.write_policy;
        setPolicy(`${policyText?.store_when || ""} Caps / 15m: ${JSON.stringify(policyText?.caps || {})}`);
        await loadItems();
      } catch (error) {
        if (!cancelled) setErr(error instanceof Error ? error.message : "Could not load memory");
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  async function addItem() {
    setStatus("");
    try {
      const data = await api<{ status?: string }>("/api/memory/items", {
        method: "POST",
        body: {
          pod: writePod,
          kind: writeKind || writeKinds[0] || "",
          title: title.trim(),
          body: body.trim(),
          company: company.trim() || null,
        },
      });
      setTitle("");
      setBody("");
      setCompany("");
      await loadItems();
      setStatus(data.status === "exists" ? "Already stored." : "Stored.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not store");
    }
  }

  async function solidify(id: string) {
    setErr("");
    try {
      await api(`/api/memory/items/${encodeURIComponent(id)}/solidify`, { method: "POST" });
      await loadItems();
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not solidify");
    }
  }

  return (
    <AppShell title="Memory pods" scroll="page" path="/admin/memory">
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5">
        <p className="m-0 text-sm text-muted-foreground">{who}</p>
        <section className="grid gap-3 border border-border bg-card p-4 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            Pod
            <select id="write-pod" className={selectClass} value={writePod} onChange={(event) => setWritePod(event.target.value)}>
              {pods
                .filter((pod) => pod.writable !== false)
                .map((pod) => (
                  <option key={pod.id} value={pod.id}>
                    {pod.label}
                  </option>
                ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Kind
            <select id="write-kind" className={selectClass} value={writeKind} onChange={(event) => setWriteKind(event.target.value)}>
              {writeKinds.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Company
            <Input id="write-company" value={company} onChange={(event) => setCompany(event.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            Title
            <Input id="write-title" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            Fact
            <Textarea id="write-body" value={body} onChange={(event) => setBody(event.target.value)} />
          </label>
          <div className="flex flex-wrap gap-2 md:col-span-2">
            <Button id="add-item" type="button" onClick={() => void addItem()}>
              Add
            </Button>
            <Button id="save-item" type="button" variant="outline" disabled>
              Save
            </Button>
            <Button id="cancel-edit" type="button" variant="outline" disabled>
              Cancel
            </Button>
          </div>
          <p id="compose-status" className="m-0 text-sm md:col-span-2">
            {status}
          </p>
        </section>
        <section className="flex flex-col gap-3 border border-border bg-card p-4">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-sm">
              Pod
              <select id="pod" className={selectClass} value={filterPod} onChange={(event) => setFilterPod(event.target.value)}>
                <option value="">visible pods</option>
                {pods.map((pod) => (
                  <option key={pod.id} value={pod.id}>
                    {pod.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Search
              <Input id="q" value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Kind
              <Input id="kind" value={filterKind} onChange={(event) => setFilterKind(event.target.value)} />
            </label>
            <Button id="load" type="button" variant="outline" onClick={() => void loadItems()}>
              Load
            </Button>
          </div>
          <p id="policy" className="m-0 text-sm text-muted-foreground">
            {policy}
          </p>
          <p id="err" className="m-0 text-sm text-destructive">
            {err}
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-sm">
              Share pod
              <select id="share-pod" className={selectClass} value={sharePod} onChange={(event) => setSharePod(event.target.value)}>
                {pods
                  .filter((pod) => pod.writable !== false)
                  .map((pod) => (
                    <option key={pod.id} value={pod.id}>
                      {pod.label}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Share kind
              <select id="share-kind" className={selectClass} value={shareKind} onChange={(event) => setShareKind(event.target.value)}>
                {(kinds[scopeOf(sharePod)] ?? []).map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input id="share-copy" type="checkbox" /> copy (leave original)
            </label>
            <Button id="share-go" type="button" variant="outline" disabled>
              Share
            </Button>
          </div>
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="px-3 py-2">Pod</th>
                  <th className="px-3 py-2">Kind</th>
                  <th className="px-3 py-2">Title</th>
                  <th className="px-3 py-2">Fact</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody id="rows">
                {items.map((item) => {
                  const canSolidify = item.pod_scope !== "worker" && (item.solidify_status || "none") === "none";
                  return (
                    <tr key={item.id} className="border-t border-border">
                      <td className="px-3 py-2">{item.pod}</td>
                      <td className="px-3 py-2">{item.kind}</td>
                      <td className="px-3 py-2">{item.title}</td>
                      <td className="px-3 py-2">{item.body}</td>
                      <td className="px-3 py-2">
                        {canSolidify ? (
                          <Button type="button" variant="outline" data-solidify={item.id} onClick={() => void solidify(item.id)}>
                            Solidify
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
