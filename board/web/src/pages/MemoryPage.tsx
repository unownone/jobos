import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { RecordCard, RecordDeck, RecordField } from "@/components/ui/record-card";
import { Table, Td, Th } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

type Pod = { id: string; label: string; writable?: boolean };
function policyLine(policy: { store_when?: string; caps?: Record<string, number> } | undefined): string {
  const when = policy?.store_when?.trim() ?? "";
  const caps = Object.entries(policy?.caps ?? {});
  const capText = caps.length === 0 ? "No 15-minute caps." : `15-minute caps: ${caps.map(([name, count]) => `${name} ${count}`).join(", ")}.`;
  return [when, capText].filter(Boolean).join(" ");
}

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

function allowedKind(podId: string, current: string, catalog: Record<string, string[]>): string {
  const allowed = catalog[scopeOf(podId)] ?? [];
  if (current && allowed.includes(current)) return current;
  return allowed[0] ?? "";
}

export function MemoryPage() {
  const [who, setWho] = useState("");
  const [conn, setConn] = useState<ShellConn>("signing in");
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
  const [shareCopy, setShareCopy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [sharingId, setSharingId] = useState<string | null>(null);

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
        setConn("signed in");
        const podData = await api<{ pods?: Pod[]; kinds?: Record<string, string[]>; write_policy?: { store_when?: string; caps?: Record<string, number> } }>(
          "/api/memory/pods",
        );
        if (cancelled) return;
        const list = podData.pods ?? [];
        setPods(list);
        setKinds(podData.kinds ?? {});
        const writable = list.filter((pod) => pod.writable !== false);
        const first = writable[0]?.id ?? "";
        const firstKind = (podData.kinds?.[scopeOf(first)] ?? [])[0] ?? "";
        setWritePod(first);
        setSharePod(first);
        setWriteKind((current) => current || firstKind);
        setShareKind((current) => current || firstKind);
        setPolicy(policyLine(podData.write_policy));
        await loadItems();
      } catch (error) {
        if (!cancelled) {
          setErr(error instanceof Error ? error.message : "Could not load memory");
          setConn((current) => (current === "signed in" ? current : "sign in required"));
        }
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

  function startEdit(item: Item) {
    setEditingId(item.id);
    setSharingId(null);
    setTitle(item.title ?? "");
    setBody(item.body ?? "");
    if (item.pod) setWritePod(item.pod);
    if (item.kind) setWriteKind(item.kind);
    setStatus("Editing.");
    setErr("");
  }

  function cancelEdit() {
    setEditingId(null);
    setTitle("");
    setBody("");
    setCompany("");
    setStatus("");
  }

  async function saveItem() {
    if (!editingId) return;
    setStatus("");
    try {
      await api(`/api/memory/items/${encodeURIComponent(editingId)}`, {
        method: "PATCH",
        body: { title: title.trim(), body: body.trim() },
      });
      setEditingId(null);
      setTitle("");
      setBody("");
      setCompany("");
      await loadItems();
      setStatus("Updated.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not save");
    }
  }

  async function removeItem(id: string) {
    if (!window.confirm("Delete this memory?")) return;
    setErr("");
    try {
      await api(`/api/memory/items/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (editingId === id) cancelEdit();
      if (sharingId === id) setSharingId(null);
      await loadItems();
      setStatus("Deleted.");
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not delete");
    }
  }

  async function shareItem() {
    if (!sharingId) return;
    setErr("");
    try {
      await api(`/api/memory/items/${encodeURIComponent(sharingId)}/move`, {
        method: "POST",
        body: { pod: sharePod, copy: shareCopy, kind: shareKind || undefined },
      });
      setSharingId(null);
      await loadItems();
      setStatus(shareCopy ? "Copied." : "Moved.");
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not share");
    }
  }

  return (
    <AppShell title="Memory pods" scroll="page" path="/admin/memory" who={who} conn={conn}>
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5">
        <p id="who" className="m-0 text-sm text-muted-foreground">{who}</p>
        <section className="grid gap-3 border border-border bg-card p-4 md:grid-cols-2">
          <Field>
            Pod
            <NativeSelect
              id="write-pod"
              value={writePod}
              onChange={(next) => {
                setWritePod(next);
                setWriteKind((current) => allowedKind(next, current, kinds));
              }}
              options={pods
                .filter((pod) => pod.writable !== false)
                .map((pod) => ({ value: pod.id, label: pod.label }))}
            />
          </Field>
          <Field>
            Kind
            <NativeSelect
              id="write-kind"
              value={writeKind}
              onChange={setWriteKind}
              options={writeKinds.map((kind) => ({ value: kind, label: kind }))}
            />
          </Field>
          <Field>
            Company
            <Input id="write-company" value={company} onChange={(event) => setCompany(event.target.value)} />
          </Field>
          <Field>
            Title
            <Input id="write-title" value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field className="md:col-span-2">
            Fact
            <Textarea id="write-body" value={body} onChange={(event) => setBody(event.target.value)} />
          </Field>
          <div className="flex flex-wrap gap-2 md:col-span-2">
            <Button id="add-item" type="button" onClick={() => void addItem()}>
              Add
            </Button>
            <Button id="save-item" type="button" variant="outline" disabled={!editingId} onClick={() => void saveItem()}>
              Save
            </Button>
            <Button id="cancel-edit" type="button" variant="outline" disabled={!editingId} onClick={cancelEdit}>
              Cancel
            </Button>
          </div>
          <p id="compose-status" className="m-0 text-sm md:col-span-2">
            {status}
          </p>
        </section>
        <section className="flex flex-col gap-3 border border-border bg-card p-4">
          <div className="flex flex-wrap items-end gap-2">
            <Field>
              Pod
              <NativeSelect
                id="pod"
                value={filterPod}
                className="w-auto shrink-0"
                onChange={setFilterPod}
                options={[
                  { value: "", label: "visible pods" },
                  ...pods.map((pod) => ({ value: pod.id, label: pod.label })),
                ]}
              />
            </Field>
            <Field>
              Search
              <Input id="q" value={query} onChange={(event) => setQuery(event.target.value)} />
            </Field>
            <Field>
              Kind
              <Input id="kind" value={filterKind} onChange={(event) => setFilterKind(event.target.value)} />
            </Field>
            <Button id="load" type="button" variant="outline" onClick={() => void loadItems()}>
              Load
            </Button>
          </div>
          <p id="policy" className="m-0 text-sm text-muted-foreground">
            {policy}
          </p>
          <p className="m-0 text-sm text-muted-foreground">
            Rows update through /api/memory/items/{"{id}"}. Share and move use /move.
          </p>
          <p id="err" className="m-0 text-sm text-destructive">
            {err}
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <Field>
              Share pod
              <NativeSelect
                id="share-pod"
                value={sharePod}
                className="w-auto shrink-0"
                onChange={setSharePod}
                options={pods
                  .filter((pod) => pod.writable !== false)
                  .map((pod) => ({ value: pod.id, label: pod.label }))}
              />
            </Field>
            <Field>
              Share kind
              <NativeSelect
                id="share-kind"
                value={shareKind}
                className="w-auto shrink-0"
                onChange={setShareKind}
                options={(kinds[scopeOf(sharePod)] ?? []).map((kind) => ({ value: kind, label: kind }))}
              />
            </Field>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <Checkbox id="share-copy" checked={shareCopy} onChange={(event) => setShareCopy(event.target.checked)} />
              copy (leave original)
            </label>
            <Button id="share-go" type="button" variant="outline" data-share={sharingId ?? "pending"} disabled={!sharingId} onClick={() => void shareItem()}>
              Share
            </Button>
            <span hidden data-edit="" data-solidify="" data-delete="" />
          </div>
          {items.length === 0 ? <p className="m-0 text-sm text-muted-foreground">No facts in this view.</p> : null}
          <RecordDeck>
            {items.map((item) => {
              const canSolidify = item.pod_scope !== "worker" && (item.solidify_status || "none") === "none";
              return (
                <RecordCard
                  key={item.id}
                  title={item.title || "Memory"}
                  subtitle={item.body || ""}
                  actions={
                    <>
                      <Button type="button" variant="outline" onClick={() => startEdit(item)}>
                        Edit
                      </Button>
                      <Button type="button" variant="outline" onClick={() => setSharingId(item.id)}>
                        Share
                      </Button>
                      {canSolidify ? (
                        <Button type="button" variant="outline" onClick={() => void solidify(item.id)}>
                          Solidify
                        </Button>
                      ) : null}
                      <Button type="button" variant="destructive" onClick={() => void removeItem(item.id)}>
                        Delete
                      </Button>
                    </>
                  }
                >
                  <RecordField label="Pod" value={item.pod || ""} />
                  <RecordField label="Kind" value={item.kind || ""} />
                </RecordCard>
              );
            })}
          </RecordDeck>
          <div className="min-w-0 overflow-x-auto max-[720px]:hidden">
            <Table>
              <thead>
                <tr>
                  <Th className="w-[16%] max-[959px]:hidden">Pod</Th>
                  <Th className="w-[16%] max-[959px]:hidden">Kind</Th>
                  <Th className="w-[20%]">Title</Th>
                  <Th className="w-[22%]">Fact</Th>
                  <Th className="w-[26%]"></Th>
                </tr>
              </thead>
              <tbody id="rows">
                {items.map((item) => {
                  const canSolidify = item.pod_scope !== "worker" && (item.solidify_status || "none") === "none";
                  return (
                    <tr key={item.id} className="border-t border-border">
                      <Td truncate={false} className="max-[959px]:hidden break-all" title={item.pod}>{item.pod}</Td>
                      <Td truncate={false} className="max-[959px]:hidden break-words" title={item.kind}>{item.kind}</Td>
                      <Td truncate={false} className="break-words" title={item.title}>{item.title}</Td>
                      <Td truncate={false} className="break-words" title={item.body}>{item.body}</Td>
                      <Td truncate={false}>
                        <div className="flex flex-wrap gap-2">
                          <Button type="button" variant="outline" data-edit={item.id} onClick={() => startEdit(item)}>
                            Edit
                          </Button>
                          <Button type="button" variant="outline" data-share={item.id} onClick={() => setSharingId(item.id)}>
                            Share
                          </Button>
                          {canSolidify ? (
                            <Button type="button" variant="outline" data-solidify={item.id} onClick={() => void solidify(item.id)}>
                              Solidify
                            </Button>
                          ) : null}
                          <Button type="button" variant="destructive" data-delete={item.id} onClick={() => void removeItem(item.id)}>
                            Delete
                          </Button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
