import { useEffect, useState, type FormEvent } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { RecordCard, RecordDeck } from "@/components/ui/record-card";
import { Table, Td, Th } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

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
  const [track, setTrack] = useState("discovery");
  const [mode, setMode] = useState("owner_then_agents");

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
              <Field>
                Track
                <NativeSelect
                  id="track"
                  name="track"
                  value={track}
                  onChange={setTrack}
                  options={[
                    { value: "discovery", label: "discovery" },
                    { value: "application", label: "application" },
                    { value: "outreach", label: "outreach" },
                    { value: "maintenance", label: "maintenance" },
                  ]}
                />
              </Field>
              <Field>
                Mode
                <NativeSelect
                  id="mode"
                  name="mode"
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "owner_then_agents", label: "owner_then_agents" },
                    { value: "owner_only", label: "owner_only" },
                    { value: "agents_only", label: "agents_only" },
                  ]}
                />
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field>
                Max redemptions
                <Input id="max" name="max" type="number" min={1} max={64} defaultValue={8} />
              </Field>
              <Field>
                TTL hours
                <Input id="ttl" name="ttl" type="number" min={1} max={720} defaultValue={72} />
              </Field>
            </div>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <Checkbox id="multi" name="multi" />
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
              <Field htmlFor="prompt">
                Agent prompt (copy this with the join link)
              </Field>
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
          <RecordDeck>
            {invites.map((invite) => (
              <RecordCard
                key={invite.id}
                title={invite.track || ""}
                subtitle={invite.mode || ""}
                actions={
                  inviteRevoked(invite) ? (
                    <span className="text-sm text-muted-foreground">revoked</span>
                  ) : (
                    <Button type="button" variant="outline" onClick={() => void revoke(invite.id)}>
                      Revoke
                    </Button>
                  )
                }
              />
            ))}
          </RecordDeck>
          <div className="min-w-0 overflow-x-auto max-[720px]:hidden">
            <Table>
              <thead>
                <tr>
                  <Th className="w-[34%]">Track</Th>
                  <Th className="w-[40%]">Mode</Th>
                  <Th className="w-[26%]"></Th>
                </tr>
              </thead>
              <tbody id="rows">
                {invites.map((invite) => (
                  <tr key={invite.id} className="border-t border-border">
                    <Td title={invite.track}>{invite.track}</Td>
                    <Td title={invite.mode}>{invite.mode}</Td>
                    <Td truncate={false}>
                      {inviteRevoked(invite) ? (
                        "revoked"
                      ) : (
                        <Button type="button" variant="outline" onClick={() => void revoke(invite.id)}>
                          Revoke
                        </Button>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
