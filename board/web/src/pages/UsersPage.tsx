import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { logout } from "@/components/shell/logout";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

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
  const [users, setUsers] = useState<DirectoryUser[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        await api("/api/presence/heartbeat", { method: "POST", body: { status_hint: "logged_in" } });
        const data = await api<{ users?: DirectoryUser[] }>("/api/users");
        if (cancelled) return;
        setUsers(data.users ?? []);
        setWho(`${data.users?.length ?? 0} people in the directory`);
      } catch (error) {
        if (!cancelled) setWho(error instanceof Error ? error.message : "Admin or maintenance session required.");
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell title="Directory" subtitle="jobOS Harness" scroll="page" path="/admin/users">
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5">
        <div className="flex items-center justify-between gap-3">
          <p id="who" className="m-0 text-sm text-muted-foreground">
            {who}
          </p>
          <Button id="logout" type="button" variant="outline" onClick={() => void logout()}>
            Log out
          </Button>
        </div>
        <div className="min-w-0 overflow-x-auto border border-border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-card">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2">Track</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Model</th>
                <th className="px-3 py-2">Harness</th>
                <th className="px-3 py-2">Bed</th>
                <th className="px-3 py-2">Last active</th>
                <th className="px-3 py-2">Task</th>
              </tr>
            </thead>
            <tbody id="rows">
              {users.map((user) => (
                <tr key={user.user_id || user.display_name} className="border-t border-border">
                  <td className="px-3 py-2">{user.display_name || user.user_id}</td>
                  <td className="px-3 py-2">{user.kind}</td>
                  <td className="px-3 py-2">
                    {user.track} / {user.role}
                  </td>
                  <td className="px-3 py-2">{user.status}</td>
                  <td className="px-3 py-2">{user.model}</td>
                  <td className="px-3 py-2">{user.harness}</td>
                  <td className="px-3 py-2">{user.bed}</td>
                  <td className="px-3 py-2">{user.last_active || user.last_seen}</td>
                  <td className="px-3 py-2">{user.current_task?.id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </AppShell>
  );
}
