import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { RecordCard, RecordDeck, RecordField } from "@/components/ui/record-card";
import { Table, Td, Th } from "@/components/ui/table";
import { api } from "@/lib/api";

function lane(track?: string, role?: string): string {
  const left = track?.trim() ?? "";
  const right = role?.trim() ?? "";
  if (left && right) return `${left} / ${right}`;
  return left || right;
}

function seenLabel(value?: string): string {
  const text = value?.trim() ?? "";
  const prefix = "Last active:";
  if (text.toLowerCase().startsWith(prefix.toLowerCase())) return text.slice(prefix.length).trim();
  return text;
}

type DirectoryUser = {
  user_id?: string;
  display_name?: string;
  kind?: string;
  track?: string;
  role?: string;
  status?: string;
  model?: string;
  harness?: string;
  bed?: string;
  last_active?: string;
  last_seen?: string;
  current_task?: { id?: string };
};

export function UsersPage() {
  const [who, setWho] = useState("Checking session…");
  const [conn, setConn] = useState<ShellConn>("signing in");
  const [users, setUsers] = useState<DirectoryUser[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        await api("/api/presence/heartbeat", { method: "POST", body: { status_hint: "logged_in" } });
        const data = await api<{ users?: DirectoryUser[] }>("/api/users");
        if (cancelled) return;
        setUsers(data.users ?? []);
        const count = data.users?.length ?? 0;
        setWho(`${count} ${count === 1 ? "person" : "people"} in the directory`);
        setConn("signed in");
      } catch (error) {
        if (!cancelled) {
          setWho(error instanceof Error ? error.message : "Admin or maintenance session required.");
          setConn("sign in required");
        }
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell title="Directory" subtitle="jobOS Harness" scroll="page" path="/admin/users" who={who} conn={conn}>
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5">
        <p id="who" className="m-0 text-sm text-muted-foreground">
          {who}
        </p>
        <RecordDeck>
          {users.map((user) => {
            const name = user.display_name || user.user_id || "";
            const track = lane(user.track, user.role);
            const seen = seenLabel(user.last_active || user.last_seen);
            return (
              <RecordCard key={user.user_id || user.display_name} title={name} subtitle={user.kind || ""}>
                <RecordField label="Track" value={track} />
                <RecordField label="Status" value={user.status || ""} />
                <RecordField label="Model" value={user.model || ""} />
                <RecordField label="Harness" value={user.harness || ""} />
                <RecordField label="Bed" value={user.bed || ""} />
                <RecordField label="Last active" value={seen} />
                <RecordField label="Task" value={user.current_task?.id || ""} />
              </RecordCard>
            );
          })}
        </RecordDeck>
        <div className="min-w-0 overflow-x-auto border border-border bg-card max-[720px]:hidden">
          <Table>
            <thead className="sticky top-0 bg-card">
              <tr>
                <Th className="w-[16%] max-[959px]:w-[46%]">Name</Th>
                <Th className="w-[9%] max-[959px]:w-[27%]">Kind</Th>
                <Th className="w-[14%] max-[959px]:hidden">Track</Th>
                <Th className="w-[9%] max-[959px]:w-[27%]">Status</Th>
                <Th className="w-[11%] max-[959px]:hidden">Model</Th>
                <Th className="w-[9%] max-[959px]:hidden">Harness</Th>
                <Th className="w-[8%] max-[959px]:hidden">Bed</Th>
                <Th className="w-[18%] max-[959px]:hidden">Last active</Th>
                <Th className="max-[959px]:hidden">Task</Th>
              </tr>
            </thead>
            <tbody id="rows">
              {users.map((user) => {
                const name = user.display_name || user.user_id || "";
                const track = lane(user.track, user.role);
                const seen = seenLabel(user.last_active || user.last_seen);
                return (
                  <tr key={user.user_id || user.display_name} className="border-t border-border">
                    <Td title={name}>{name}</Td>
                    <Td title={user.kind}>{user.kind}</Td>
                    <Td className="max-[959px]:hidden" title={track}>{track}</Td>
                    <Td title={user.status}>{user.status}</Td>
                    <Td className="max-[959px]:hidden" title={user.model}>{user.model}</Td>
                    <Td className="max-[959px]:hidden" title={user.harness}>{user.harness}</Td>
                    <Td className="max-[959px]:hidden" title={user.bed}>{user.bed}</Td>
                    <Td className="max-[959px]:hidden" title={seen}>{seen}</Td>
                    <Td className="max-[959px]:hidden" title={user.current_task?.id}>{user.current_task?.id}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      </main>
    </AppShell>
  );
}
