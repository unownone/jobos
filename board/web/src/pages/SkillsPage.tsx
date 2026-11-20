import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Table, Td, Th } from "@/components/ui/table";
import { NativeSelect } from "@/components/ui/select";
import { api } from "@/lib/api";

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
          <Table>
            <thead>
              <tr>
                <Th>Slug</Th>
                <Th>Role</Th>
                <Th className="max-[959px]:hidden">Tags</Th>
                <Th className="max-[959px]:hidden">Scope</Th>
                <Th className="max-[959px]:hidden">Status</Th>
              </tr>
            </thead>
            <tbody id="skills">
              {skills.map((skill) => (
                <tr key={skill.slug} className="border-t border-border">
                  <Td title={skill.slug}>{skill.slug}</Td>
                  <Td title={skill.role}>{skill.role}</Td>
                  <Td className="max-[959px]:hidden" title={(skill.tags ?? []).join(", ")}>{(skill.tags ?? []).join(", ")}</Td>
                  <Td className="max-[959px]:hidden" title={skill.scope}>{skill.scope}</Td>
                  <Td className="max-[959px]:hidden" title={skill.status}>{skill.status}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        <div className="min-w-0 overflow-x-auto border border-border bg-card">
          <Table>
            <thead>
              <tr>
                <Th>Recording</Th>
                <Th>Skill</Th>
                <Th className="max-[959px]:hidden">Scope</Th>
                <Th className="max-[959px]:hidden">Status</Th>
                <Th className="max-[959px]:hidden">Note</Th>
              </tr>
            </thead>
            <tbody id="recordings">
              {recordings.map((recording, index) => (
                <tr key={recording.id || index} className="border-t border-border">
                  <Td title={recording.id}>{recording.id}</Td>
                  <Td title={recording.skill}>{recording.skill}</Td>
                  <Td className="max-[959px]:hidden" title={recording.scope}>{recording.scope}</Td>
                  <Td className="max-[959px]:hidden" title={recording.status}>{recording.status}</Td>
                  <Td className="max-[959px]:hidden" title={recording.note}>{recording.note}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </main>
    </AppShell>
  );
}
