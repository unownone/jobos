import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

const selectClass =
  "flex min-h-[2.75rem] rounded-md border border-input bg-background px-3 text-sm text-foreground";

type Skill = {
  slug: string;
  role: string;
  tags?: string[];
  scope: string;
  status: string;
};

type Recording = {
  id?: string;
  skill?: string;
  scope?: string;
  status?: string;
  note?: string;
};

export function SkillsPage() {
  const [who, setWho] = useState("Checking session…");
  const [conn, setConn] = useState<ShellConn>("signing in");
  const [tag, setTag] = useState("");
  const [scope, setScope] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [msg, setMsg] = useState("");

  async function loadSkills(nextTag = tag, nextScope = scope) {
    const params = new URLSearchParams();
    if (nextTag) params.set("tag", nextTag);
    if (nextScope) params.set("scope", nextScope);
    const data = await api<{ skills?: Skill[] }>(`/api/registry/skills?${params.toString()}`);
    setSkills(data.skills ?? []);
  }

  async function loadRecordings() {
    try {
      const data = await api<{ recordings?: Recording[] }>("/api/registry/recordings");
      setRecordings(data.recordings ?? []);
    } catch (error) {
      setRecordings([]);
      setMsg(error instanceof Error ? error.message : "Could not load recordings");
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const me = await api<{ display_name?: string; role?: string; track?: string; kind?: string }>("/api/auth/me");
        if (cancelled) return;
        setWho(`${me.display_name || me.role || "signed in"} · ${me.track || me.kind || ""}`);
        setConn("signed in");
        await loadSkills();
        await loadRecordings();
      } catch (error) {
        if (!cancelled) {
          setWho(error instanceof Error ? error.message : "Sign in required.");
          setConn("sign in required");
        }
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  async function seed() {
    setMsg("");
    try {
      const data = await api<{ counts?: Record<string, number> }>("/api/registry/seed", { method: "POST" });
      setMsg(`Seeded: ${JSON.stringify(data.counts || {})}`);
      await loadSkills();
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "Seed failed");
    }
  }

  return (
    <AppShell title="Skill registry" scroll="page" path="/admin/skills" who={who} conn={conn}>
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-5">
        <p className="m-0 text-sm text-muted-foreground">
          GitHub starters seed shared skills. Local forks stay on the owning bot. Only maintainer consumes skill.record after proctor.
        </p>
        <p id="who" className="m-0 text-sm text-muted-foreground">
          {who}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select id="tag" className={selectClass} aria-label="Tag" value={tag} onChange={(event) => setTag(event.target.value)}>
            <option value="">all tags</option>
            <option value="source">source</option>
            <option value="apply">apply</option>
            <option value="outreach">outreach</option>
          </select>
          <select id="scope" className={selectClass} aria-label="Scope" value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="">shared + mine</option>
            <option value="shared">shared</option>
            <option value="local">local</option>
          </select>
          <Button
            id="reload"
            type="button"
            variant="outline"
            onClick={() => {
              void loadSkills();
              void loadRecordings();
            }}
          >
            Reload
          </Button>
          <Button id="seed" type="button" onClick={() => void seed()}>
            Seed
          </Button>
        </div>
        <p id="msg" className="m-0 text-sm">
          {msg}
        </p>
        <div className="min-w-0 overflow-x-auto border border-border bg-card">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th className="px-3 py-2">Slug</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Tags</th>
                <th className="px-3 py-2">Scope</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody id="skills">
              {skills.map((skill) => (
                <tr key={skill.slug} className="border-t border-border">
                  <td className="px-3 py-2">{skill.slug}</td>
                  <td className="px-3 py-2">{skill.role}</td>
                  <td className="px-3 py-2">{(skill.tags ?? []).join(", ")}</td>
                  <td className="px-3 py-2">{skill.scope}</td>
                  <td className="px-3 py-2">{skill.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="min-w-0 overflow-x-auto border border-border bg-card">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th className="px-3 py-2">Recording</th>
                <th className="px-3 py-2">Skill</th>
                <th className="px-3 py-2">Scope</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Note</th>
              </tr>
            </thead>
            <tbody id="recordings">
              {recordings.map((recording, index) => (
                <tr key={recording.id || index} className="border-t border-border">
                  <td className="px-3 py-2">{recording.id}</td>
                  <td className="px-3 py-2">{recording.skill}</td>
                  <td className="px-3 py-2">{recording.scope}</td>
                  <td className="px-3 py-2">{recording.status}</td>
                  <td className="px-3 py-2">{recording.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </AppShell>
  );
}
