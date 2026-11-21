import { useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "./api";
import { LABELS, STEP1, STEP2, STEP3, emptyProfile, fromYaml, toYaml, type ProfileKey, type ProfileValues } from "./profile";
import { useSession, type SessionMe } from "./session";


const STATUSES = ["discovered", "shortlisted", "apply_ready", "applied", "outreach_ready", "rejected", "closed_withdrawn"];
const TRACKS = ["discovery", "application", "outreach", "maintenance"];
const KINDS = {
  worker: ["working_note", "reminder", "fact"],
  track: ["portal_quirk", "blocker", "tool_failure", "company_note", "process_note", "person_hint", "search_coverage"],
  common: ["process_note", "tool_failure", "catalog_note", "candidate_constraint", "hub_note"],
};

type JobRejection = { by?: string; company_remarks?: string; user_remarks?: string };
type JobRow = {
  id: string;
  company?: string;
  title?: string;
  notes?: string;
  status?: string;
  stopped?: boolean;
  rejection?: JobRejection | null;
};
type JobDraft = {
  company: string;
  title: string;
  notes: string;
  status: string;
  rejection_by: string;
  company_remarks: string;
  user_remarks: string;
};
type MemoryScope = keyof typeof KINDS;
type MemoryItem = { id: string; pod: string; kind: string; title: string; body: string };
type InviteRow = { id: string; track: string; revoked_at?: string | null; redemptions?: number; max_redemptions?: number };
type AgentRow = { id: string; display_name?: string; track?: string; kind?: string };
type SkillRow = { id: string; slug?: string; name?: string; tags?: string[] };

function loginPath(next: string | null | undefined) {
  const path = next && next.startsWith("/") && !next.startsWith("//") ? next : "/board";
  return `/login?next=${encodeURIComponent(path)}`;
}

export function Gate({ children }: { children: (me: SessionMe) => ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.status === "loading") return <p>Checking session</p>;
  if (session.status === "out") {
    const next = `${location.pathname}${location.search || ""}`;
    return <Navigate to={loginPath(next)} replace />;
  }
  return children(session.me);
}

function Logout() {
  const navigate = useNavigate();
  async function out() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      // A missing session still leaves the login page.
    }
    navigate("/login");
  }
  return <button id="logoutBtn" type="button" data-hub-logout onClick={out}>Log out</button>;
}

function Who({ me, id }: { me: SessionMe; id: string }) {
  const name = me?.user?.display_name || me?.actor || "admin";
  const role = me?.role || me?.kind || "admin";
  return <p id={id}>Signed in as {name} · {role}</p>;
}

function Shell({ me, who = "who", children }: { me?: SessionMe; who?: string; children: ReactNode }) {
  return (
    <div className="shell">
      <header className="top">
        <h1>jobOS</h1>
        <nav>
          <Link to="/board">Board</Link>
          <Link to="/onboarding">Onboarding</Link>
          <Link to="/admin">Invites</Link>
          <Link to="/admin/skills">Skills</Link>
          <Link to="/admin/memory">Memory</Link>
          {me ? <Logout /> : <Link to="/login">Log in</Link>}
        </nav>
      </header>
      {me ? <Who me={me} id={who} /> : null}
      {children}
    </div>
  );
}

export function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const signup = (event.nativeEvent as SubmitEvent).submitter instanceof HTMLElement
      && (event.nativeEvent as SubmitEvent).submitter?.id === "signupBtn";
    try {
      const path = signup ? "/api/auth/signup" : "/api/auth/login";
      await api(path, { method: "POST", body: JSON.stringify({ username, password }) });
      const next = params.get("next") || "/board";
      const safe = next.startsWith("/") && !next.startsWith("//") ? next : "/board";
      navigate(signup ? "/onboarding" : safe);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  return (
    <Shell>
      <form className="stack" onSubmit={submit}>
        <h2>Log in</h2>
        <input id="username" placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input id="password" placeholder="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <p id="err" className="error">{error}</p>
        <div className="row">
          <button id="loginBtn" type="submit">Log in</button>
          <button id="signupBtn" type="submit">Create account</button>
        </div>
      </form>
    </Shell>
  );
}

export function AdminSignup() {
  const session = useSession();
  const [boot, setBoot] = useState<boolean | null>(null);
  useEffect(() => {
    api<{ admin_bootstrapped?: boolean }>("/health").then((health) => setBoot(Boolean(health.admin_bootstrapped))).catch(() => setBoot(true));
  }, []);
  if (session.status === "loading" || boot === null) return <p>Checking session</p>;
  if (session.status === "in") return <Navigate to="/onboarding" replace />;
  if (boot) return <Navigate to="/login" replace />;
  return <Login />;
}

function Field({ id, value, onChange, area }: { id: string; value: string; onChange: (id: string, value: string) => void; area?: boolean }) {
  const common = {
    id,
    value: value || "",
    onChange: (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(id, e.target.value),
  };
  return (
    <label>
      {(LABELS as Record<string, string>)[id] || id}
      {area ? <textarea {...common} /> : <input {...common} />}
    </label>
  );
}

export function Onboarding({ me }: { me: SessionMe }) {
  const navigate = useNavigate();
  const [values, setValues] = useState<ProfileValues>(emptyProfile);
  const [step, setStep] = useState(1);
  const [showAll, setShowAll] = useState(false);
  const [offerResume, setOfferResume] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    api<{ yaml?: string }>("/api/candidate").then((data) => {
      if (data.yaml) {
        setValues(fromYaml(data.yaml));
        setShowAll(true);
      }
    }).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  function set(id: ProfileKey, value: string) {
    setValues((prev) => ({ ...prev, [id]: value }));
  }

  function advance(from: number) {
    if (showAll) return;
    if (from === 1 && (!values.full_name.trim() || !values.email.trim())) {
      setError("Full name and email are required");
      return;
    }
    if (from === 2 && (!values.titles.trim() || !values.locations.trim())) {
      setError("A title and a location are required");
      return;
    }
    setError("");
    setStep(from + 1);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!values.full_name.trim() || !values.email.trim() || !values.titles.trim() || !values.locations.trim()) {
      setError("Name, email, a title, and a location are required");
      return;
    }
    const nextValues = { ...values, revision: String(Number(values.revision || "0") + 1) };
    try {
      await api("/api/candidate", { method: "PUT", body: toYaml(nextValues), headers: { "Content-Type": "text/yaml" } });
      setValues(nextValues);
      setNote("Profile saved.");
      setOfferResume(true);
      if (!showAll) setStep(4);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function upload() {
    const input = document.getElementById("resume") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) {
      setError("Choose a resume PDF");
      return;
    }
    const bytes = await file.arrayBuffer();
    await api("/api/candidate/resume", { method: "PUT", body: bytes, headers: { "Content-Type": "application/pdf" } });
    navigate("/board");
  }

  function fieldsFor(which: number, ids: readonly ProfileKey[]) {
    return (
      <div id={`step${which}`}>
        {ids.map((id) => (
          <Field
            key={id}
            id={id === "locations" ? "locations_t" : id}
            value={values[id] || ""}
            onChange={(key, value) => set((key === "locations_t" ? "locations" : key) as ProfileKey, value)}
            area={id === "must_haves" || id === "deal_breakers" || id === "highlights"}
          />
        ))}
      </div>
    );
  }

  const reviewing = step === 4 && !showAll;
  return (
    <Shell me={me}>
      <form id="formPanel" className="stack wide" onSubmit={save}>
        <h2>Candidate</h2>
        <p id="revLine">revision {values.revision || "pending"}</p>
        {reviewing ? (
          <div id="step4">
            <p>Profile is saved. Add a resume or open the board.</p>
            <input id="resume" type="file" accept="application/pdf" />
            <div className="row">
              <button id="uploadResume" type="button" onClick={upload}>Upload resume</button>
              <button id="skipResume" type="button" onClick={() => navigate("/board")}>Skip resume</button>
            </div>
          </div>
        ) : (
          <>
            {(showAll || step === 1) ? fieldsFor(1, STEP1) : null}
            {(showAll || step === 2) ? fieldsFor(2, STEP2) : null}
            {(showAll || step === 3) ? fieldsFor(3, STEP3) : null}
            {offerResume && showAll ? (
              <div id="step4">
                <p>Profile is saved. Add a resume or open the board.</p>
                <input id="resume" type="file" accept="application/pdf" />
                <div className="row">
                  <button id="uploadResume" type="button" onClick={upload}>Upload resume</button>
                  <button id="skipResume" type="button" onClick={() => navigate("/board")}>Skip resume</button>
                </div>
              </div>
            ) : null}
          </>
        )}
        <p id="ok">{note}</p>
        <p id="err" className="error">{error}</p>
        {(showAll || step === 1) && !reviewing ? <button id="to2" type="button" onClick={() => advance(1)}>Continue</button> : null}
        {(showAll || step === 2) && !reviewing ? <button id="to3" type="button" onClick={() => advance(2)}>Continue</button> : null}
        {(showAll || step === 3) && !reviewing ? <button id="save" type="submit">Save profile</button> : null}
      </form>
    </Shell>
  );
}

export function Home({ me }: { me: SessionMe }) {
  return (
    <Shell me={me} who="whoLabel">
      <p><Link to="/board">Open board</Link></p>
    </Shell>
  );
}

export function Board({ me }: { me: SessionMe }) {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<JobDraft | null>(null);
  const [side, setSide] = useState("");
  const [error, setError] = useState("");
  const [pausing, setPausing] = useState(false);
  const [pauseReason, setPauseReason] = useState("");

  async function load(query = q): Promise<JobRow[]> {
    const data = await api<{ jobs?: JobRow[] }>(`/api/jobs?q=${encodeURIComponent(query)}`);
    setJobs(data.jobs || []);
    return data.jobs || [];
  }

  useEffect(() => {
    load("").catch((err) => setError(err instanceof Error ? err.message : String(err)));
    const source = new EventSource("/api/stream", { withCredentials: true });
    source.onmessage = () => load().catch(() => {});
    return () => source.close();
  }, []);

  function open(job: JobRow) {
    const rejection = job.rejection && typeof job.rejection === "object" ? job.rejection : {};
    setSelected(job.id);
    setDraft({
      company: job.company || "",
      title: job.title || "",
      notes: job.notes || "",
      status: job.status || "discovered",
      rejection_by: rejection.by || "",
      company_remarks: rejection.company_remarks || "",
      user_remarks: rejection.user_remarks || "",
    });
    setSide("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !selected) return;
    const body: Record<string, unknown> = { company: draft.company, title: draft.title, notes: draft.notes, status: draft.status };
    if (draft.status === "rejected") {
      body.rejection = { by: draft.rejection_by, company_remarks: draft.company_remarks, user_remarks: draft.user_remarks };
    }
    const data = await api<{ job: JobRow }>(`/api/jobs/${selected}`, { method: "PATCH", body: JSON.stringify(body) });
    const rows = await load();
    const fresh = rows.find((job) => job.id === data.job.id) || data.job;
    open(fresh);
    setSide("Saved");
  }

  async function confirmPause() {
    await api(`/api/jobs/${selected}/pause`, { method: "POST", body: JSON.stringify({ reason: pauseReason }) });
    setPauseReason("");
    setPausing(false);
    const rows = await load();
    const fresh = rows.find((job) => job.id === selected);
    if (fresh) open(fresh);
  }

  async function resume() {
    await api(`/api/jobs/${selected}/resume`, { method: "POST", body: "{}" });
    const rows = await load();
    const fresh = rows.find((job) => job.id === selected);
    if (fresh) open(fresh);
  }

  return (
    <Shell me={me} who="whoLabel">
      <div className="row">
        <input id="q" value={q} placeholder="Search" onChange={(e) => setQ(e.target.value)} />
        <button id="refresh" type="button" onClick={() => load(q)}>Refresh</button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <div className="split">
        <table id="list">
          <thead><tr><th>Company</th><th>Title</th><th>Status</th></tr></thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} onClick={() => open(job)}>
                <td>{job.company}</td>
                <td>{job.title}</td>
                <td>{job.stopped ? "stopped" : job.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {draft ? (
          <form className="stack" onSubmit={save}>
            <input id="f_company" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} />
            <input id="f_title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            <textarea id="f_notes" value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
            <select id="f_status" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
              {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
            <select id="f_rejection_by" value={draft.rejection_by} onChange={(e) => setDraft({ ...draft, rejection_by: e.target.value })}>
              <option value="">rejection by</option>
              <option value="company">company</option>
              <option value="user">user</option>
            </select>
            <textarea id="f_company_remarks" value={draft.company_remarks} onChange={(e) => setDraft({ ...draft, company_remarks: e.target.value })} />
            <textarea id="f_user_remarks" value={draft.user_remarks} onChange={(e) => setDraft({ ...draft, user_remarks: e.target.value })} />
            <p id="sideErr">{side}</p>
            <div className="row">
              <button id="saveBtn" type="submit">Save</button>
              <button id="pauseBtn" type="button" onClick={() => setPausing(true)}>Pause</button>
              <button id="resumeBtn" type="button" onClick={resume}>Resume</button>
            </div>
            {pausing ? (
              <div className="row">
                <input id="laneReason" value={pauseReason} placeholder="Why pause" onChange={(e) => setPauseReason(e.target.value)} />
                <button id="laneConfirm" type="button" onClick={confirmPause}>Confirm pause</button>
              </div>
            ) : null}
          </form>
        ) : null}
      </div>
    </Shell>
  );
}

export function Invites({ me }: { me: SessionMe }) {
  const [track, setTrack] = useState("discovery");
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [fresh, setFresh] = useState<{ join_url: string } | null>(null);
  const [error, setError] = useState("");

  async function load() {
    const data = await api<{ invites?: InviteRow[] }>("/api/invites");
    setInvites(data.invites || []);
  }
  useEffect(() => { load().catch((err) => setError(err instanceof Error ? err.message : String(err))); }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = await api<{ join_url: string }>("/api/invites", { method: "POST", body: JSON.stringify({ track, mode: "owner_then_agents" }) });
    setFresh(data);
    await load();
  }

  async function revoke(id: string) {
    await api(`/api/invites/${id}/revoke`, { method: "POST", body: "{}" });
    await load();
  }

  const prompt = fresh
    ? `Join ${fresh.join_url} and read AGENTS.md before you search. review the packet before any apply.`
    : "Create an invite. review the track before you share it.";

  return (
    <Shell me={me}>
      <p id="soon">review and resume tailoring land with the operator shell.</p>
      <form id="form" className="row" onSubmit={create}>
        <select id="track" value={track} onChange={(e) => setTrack(e.target.value)}>
          {TRACKS.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <button type="submit">Create invite</button>
      </form>
      {fresh ? <p id="created">Join URL (shown once): <span id="url">{fresh.join_url}</span></p> : null}
      <textarea id="prompt" readOnly value={prompt} />
      {error ? <p className="error">{error}</p> : null}
      <table id="rows">
        <tbody>
          {invites.map((inv) => (
            <tr key={inv.id}>
              <td>{inv.track}</td>
              <td>{inv.revoked_at ? "revoked" : `${inv.redemptions}/${inv.max_redemptions}`}</td>
              <td>{inv.revoked_at ? null : <button type="button" onClick={() => revoke(inv.id)}>Revoke</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  );
}

export function Users({ me }: { me: SessionMe }) {
  const [users, setUsers] = useState<AgentRow[]>([]);
  useEffect(() => { api<{ users?: AgentRow[] }>("/api/agents").then((data) => setUsers(data.users || [])).catch(() => {}); }, []);
  return (
    <Shell me={me}>
      <table id="rows">
        <tbody>
          {users.map((user) => (
            <tr key={user.id}><td>{user.display_name}</td><td>{user.track}</td><td>{user.kind}</td></tr>
          ))}
        </tbody>
      </table>
    </Shell>
  );
}

export function Skills({ me }: { me: SessionMe }) {
  const [tag, setTag] = useState("");
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [msg, setMsg] = useState("");

  async function load(next = tag) {
    const data = await api<{ skills?: SkillRow[] }>(`/api/registry/skills${next ? `?tag=${encodeURIComponent(next)}` : ""}`);
    setSkills(data.skills || []);
  }
  useEffect(() => { load("").catch(() => {}); }, []);

  async function seed() {
    const data = await api<{ seeded?: number }>("/api/registry/seed", { method: "POST", body: "{}" });
    setMsg(`Seeded ${data.seeded}`);
    await load(tag);
  }

  return (
    <Shell me={me}>
      <div className="row">
        <select id="tag" value={tag} onChange={(e) => setTag(e.target.value)}>
          <option value="">all</option>
          <option value="source">source</option>
          <option value="apply">apply</option>
          <option value="outreach">outreach</option>
        </select>
        <button id="reload" type="button" onClick={() => load(tag)}>Reload</button>
        <button id="seed" type="button" onClick={seed}>Seed</button>
      </div>
      <p id="msg">{msg}</p>
      <ul id="skills">
        {skills.map((skill) => (
          <li key={skill.id}>{skill.slug || skill.name} {JSON.stringify(skill.tags || [])}</li>
        ))}
      </ul>
    </Shell>
  );
}

export function Memory({ me }: { me: SessionMe }) {
  const [pods, setPods] = useState<string[]>(["track:discovery", "common"]);
  const [pod, setPod] = useState("track:discovery");
  const [filter, setFilter] = useState("");
  const [kind, setKind] = useState("portal_quirk");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [editing, setEditing] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    api<{ pods?: string[] }>("/api/memory/pods").then((data) => {
      const next = data.pods || [];
      if (next.length) {
        setPods(next);
        const preferred = next.find((item) => item === "track:discovery") || next[0];
        setPod(preferred);
        const scope = preferred.startsWith("track:") ? "track" : preferred === "common" ? "common" : "worker";
        setKind(KINDS[scope][0]);
      }
    }).catch(() => {});
  }, []);

  async function load(next = filter) {
    const data = await api<{ items?: MemoryItem[] }>(`/api/memory/items${next ? `?pod=${encodeURIComponent(next)}` : ""}`);
    setItems(data.items || []);
  }
  useEffect(() => { load("").catch(() => {}); }, []);

  function scopeOf(value: string): MemoryScope {
    if (value.startsWith("track:")) return "track";
    if (value === "common") return "common";
    return "worker";
  }

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await api("/api/memory/items", { method: "POST", body: JSON.stringify({ pod, kind, title, body }) });
    setStatus("Stored");
    setEditing("");
    await load(filter);
  }

  function edit(item: MemoryItem) {
    setEditing(item.id);
    setPod(item.pod);
    setKind(item.kind);
    setTitle(item.title);
    setBody(item.body);
  }

  async function save() {
    await api(`/api/memory/items/${editing}`, { method: "PATCH", body: JSON.stringify({ title, body, kind }) });
    setStatus("Updated");
    setEditing("");
    await load(filter);
  }

  const kinds = KINDS[scopeOf(pod)] || KINDS.track;
  return (
    <Shell me={me}>
      <form className="stack wide" onSubmit={add}>
        <select id="write-pod" value={pod} onChange={(e) => { setPod(e.target.value); setKind(KINDS[scopeOf(e.target.value)][0]); }}>
          {pods.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select id="write-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {kinds.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <input id="write-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea id="write-body" value={body} onChange={(e) => setBody(e.target.value)} />
        <div className="row">
          <button id="add-item" type="submit">Add</button>
          {editing ? <button id="save-item" type="button" onClick={save}>Save</button> : null}
        </div>
        <p id="compose-status">{status}</p>
      </form>
      <div className="row">
        <select id="pod" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">all</option>
          {pods.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <button id="load" type="button" onClick={() => load(filter)}>Load</button>
      </div>
      <table id="rows">
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.title}</td>
              <td>{item.body}</td>
              <td><button type="button" data-edit={item.id} onClick={() => edit(item)}>Edit</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Shell>
  );
}

export function Data({ me }: { me: SessionMe }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "jobs";
  const [rows, setRows] = useState<string[]>([]);
  const [stats, setStats] = useState("");

  useEffect(() => {
    let gone = false;
    async function run() {
      if (tab === "jobs") {
        const data = await api<{ jobs?: JobRow[] }>("/api/jobs");
        if (!gone) setRows((data.jobs || []).map((job) => `${job.company} ${job.title}`));
      } else if (tab === "people") {
        const data = await api<{ people?: { name?: string; title?: string }[] }>("/api/people");
        if (!gone) setRows((data.people || []).map((person) => `${person.name} ${person.title || ""}`));
      } else if (tab === "skills") {
        const data = await api<{ skills?: SkillRow[] }>("/api/registry/skills");
        if (!gone) setRows((data.skills || []).map((skill) => skill.slug || skill.name || ""));
      } else if (tab === "mcps") {
        const data = await api<{ mcps?: { slug?: string; name?: string; id?: string }[] }>("/api/registry/mcps");
        if (!gone) setRows((data.mcps || []).map((item) => item.slug || item.name || item.id || ""));
      } else if (tab === "memory") {
        const data = await api<{ items?: MemoryItem[] }>("/api/memory/items");
        if (!gone) setRows((data.items || []).map((item) => `${item.title} ${item.body}`));
      } else if (tab === "candidate") {
        const [profile, status] = await Promise.all([
          api<{ yaml?: string }>("/api/candidate"),
          api<{ onboarded?: boolean }>("/api/candidate/status"),
        ]);
        if (!gone) {
          setRows([profile.yaml || ""]);
          setStats(status.onboarded ? "onboarded" : "missing profile");
        }
      }
    }
    run().catch(() => {});
    return () => { gone = true; };
  }, [tab]);

  function pick(next: string) {
    setParams({ tab: next });
  }

  return (
    <Shell me={me}>
      <div className="row">
        {["jobs", "people", "candidate", "skills", "mcps", "memory"].map((name) => (
          <button key={name} type="button" data-tab={name} onClick={() => pick(name)}>{name}</button>
        ))}
      </div>
      <p id="stats">{stats}</p>
      <table id="table"><tbody>{rows.map((row, index) => <tr key={index}><td>{row}</td></tr>)}</tbody></table>
    </Shell>
  );
}

export function Join() {
  const { id } = useParams();
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [harness, setHarness] = useState("");
  const [bed, setBed] = useState("");
  const [provider, setProvider] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const secret = new URLSearchParams(window.location.search).get("s") || "";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const data = await api<{ api_key: string }>("/api/auth/join", {
        method: "POST",
        body: JSON.stringify({
          invite_id: id,
          s: secret,
          display_name: name,
          metadata: { model, harness, bed, provider, capabilities },
        }),
      });
      setKey(data.api_key);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Shell>
      <form id="form" className="stack" onSubmit={submit}>
        <h2>Join {id}</h2>
        <input id="name" placeholder="bot name" value={name} onChange={(e) => setName(e.target.value)} />
        <input id="model" placeholder="model" value={model} onChange={(e) => setModel(e.target.value)} />
        <input id="harness" placeholder="harness" value={harness} onChange={(e) => setHarness(e.target.value)} />
        <input id="bed" placeholder="bed" value={bed} onChange={(e) => setBed(e.target.value)} />
        <input id="provider" placeholder="provider" value={provider} onChange={(e) => setProvider(e.target.value)} />
        <input id="capabilities" placeholder="capabilities" value={capabilities} onChange={(e) => setCapabilities(e.target.value)} />
        <button type="submit">Redeem invite</button>
        {key ? <p id="key">API key, shown once: {key}</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </form>
    </Shell>
  );
}
