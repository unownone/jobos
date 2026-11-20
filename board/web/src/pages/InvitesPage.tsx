import { useEffect, useState, type FormEvent } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

const selectClass =
  "flex min-h-[2.75rem] w-full rounded-md border border-input bg-background px-3 text-sm text-foreground";

type Invite = {
  id: string;
  track: string;
  mode?: string;
  revoked?: boolean;
  revoked_at?: string | null;
};

function inviteRevoked(invite: Invite): boolean {
  return Boolean(invite.revoked || invite.revoked_at);
}

type Created = {
  join_url?: string;
  agent_prompt?: string;
};

export function InvitesPage() {
  const [who, setWho] = useState("Checking session…");
  const [headerWho, setHeaderWho] = useState("");
  const [conn, setConn] = useState<ShellConn>("signing in");
  const [invites, setInvites] = useState<Invite[]>([]);
  const [soon, setSoon] = useState<string[]>([]);
  const [created, setCreated] = useState("");
  const [url, setUrl] = useState("");
  const [prompt, setPrompt] = useState("");
  const [err, setErr] = useState("");

  async function loadInvites() {
    const data = await api<{ invites?: Invite[] }>("/api/invites");
    setInvites(data.invites ?? []);
  }

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const me = await api<{ user?: { email?: string }; actor?: string }>("/api/auth/me");
        if (cancelled) return;
        const name = me.user?.email || me.actor || "admin";
        setHeaderWho(name);
        setWho(`Signed in as ${name} (human admin, not a track).`);
        setConn("signed in");
        await api("/api/presence/heartbeat", { method: "POST", body: { status_hint: "logged_in" } });
        await loadInvites();
        const meta = await api<{ coming_soon_roles?: { id: string; summary?: string }[] }>("/api/meta");
        if (cancelled) return;
        const roles = meta.coming_soon_roles ?? [
          { id: "review", summary: "Will review the candidate profile/resume and give feedback on shortlisted jobs." },
          { id: "resume", summary: "Will tailor ATS-friendly resumes from the candidate profile." },
        ];
        setSoon(roles.map((row) => `${row.id} — ${row.summary || "coming soon"}`));
      } catch (error) {
        if (!cancelled) {
          setWho(error instanceof Error ? error.message : "Admin session required.");
          setConn("sign in required");
        }
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErr("");
    setCreated("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const body = await api<Created>("/api/invites", {
        method: "POST",
        body: {
          track: String(data.get("track") || "discovery"),
          mode: String(data.get("mode") || "owner_then_agents"),
          max_redemptions: Number(data.get("max") || 8),
          ttl_hours: Number(data.get("ttl") || 72),
          allow_multiple_owners: data.get("multi") === "on",
        },
      });
      const join = body.join_url || "";
      setUrl(join);
      setCreated(join ? `Copy this join link (secret shown once): ${join}` : "Invite created.");
      setPrompt(body.agent_prompt || "");
      await loadInvites();
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not create the invite");
    }
  }

  async function revoke(id: string) {
    setErr("");
    try {
      await api(`/api/invites/${encodeURIComponent(id)}/revoke`, { method: "POST" });
      await loadInvites();
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not revoke the invite");
    }
  }

  return (
    <AppShell title="jobOS Harness — Invites" scroll="page" path="/admin" who={headerWho} conn={conn}>
      <main id="main" className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-5">
        <p id="who" className="m-0 text-sm text-muted-foreground">
          {who}
        </p>
        <section className="flex flex-col gap-3 border border-border bg-card p-4">
          <h2 className="m-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">
            Create track invite
          </h2>
          <form id="form" className="flex flex-col gap-3" onSubmit={(event) => void onCreate(event)}>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm">
                Track
                <select id="track" name="track" className={selectClass} defaultValue="discovery">
                  <option value="discovery">discovery</option>
                  <option value="application">application</option>
                  <option value="outreach">outreach</option>
                  <option value="maintenance">maintenance</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Mode
                <select id="mode" name="mode" className={selectClass} defaultValue="owner_then_agents">
                  <option value="owner_then_agents">owner_then_agents</option>
                  <option value="owner_only">owner_only</option>
                  <option value="agents_only">agents_only</option>
                </select>
              </label>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-sm">
                Max redemptions
                <Input id="max" name="max" type="number" min={1} max={64} defaultValue={8} />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                TTL hours
                <Input id="ttl" name="ttl" type="number" min={1} max={720} defaultValue={72} />
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input id="multi" name="multi" type="checkbox" className="size-4" />
              Allow multiple owners on this track
            </label>
            <Button type="submit">Create invite</Button>
          </form>
          <p id="err" className="m-0 text-sm text-destructive">
            {err}
          </p>
          <p id="created" className="m-0 text-sm">
            {created}
            {url ? (
              <>
                {" "}
                <code id="url">{url}</code>
              </>
            ) : null}
          </p>
          {prompt ? (
            <div>
              <label className="mb-1 block text-sm" htmlFor="prompt">
                Agent prompt (copy this with the join link)
              </label>
              <Textarea id="prompt" readOnly value={prompt} />
            </div>
          ) : (
            <Textarea id="prompt" readOnly value="" className="hidden" />
          )}
        </section>
        <section className="border border-border bg-card p-4">
          <h2 className="mt-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">
            Coming soon
          </h2>
          <p>Review and resume roles are stubs. Do not mint invites for them.</p>
          <ul id="soon" className="text-muted-foreground">
            {soon.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
        <section className="border border-border bg-card p-4">
          <h2 className="mt-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">
            Deploy
          </h2>
          <p>
            <a href="https://railway.com/new/template?template=https://github.com/unownone/jobos">Deploy on Railway</a>
            {" · "}
            <a href="https://coolify.io">Deploy with Coolify</a> using this repo’s docker-compose.yml (Hub on 8787).
          </p>
        </section>
        <section className="border border-border bg-card p-4">
          <h2 className="mt-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">
            Existing invites
          </h2>
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  <th>Track</th>
                  <th>Mode</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="rows">
                {invites.map((invite) => (
                  <tr key={invite.id}>
                    <td>{invite.track}</td>
                    <td>{invite.mode}</td>
                    <td>
                      {inviteRevoked(invite) ? (
                        "revoked"
                      ) : (
                        <Button type="button" variant="outline" onClick={() => void revoke(invite.id)}>
                          Revoke
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
