import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api } from "./api";
import {
  HINTS,
  LABELS,
  STEP1,
  STEP2,
  STEP3,
  STEP_META,
  allTimezones,
  emptyProfile,
  fromYaml,
  systemTimezone,
  toYaml,
  type ProfileKey,
  type ProfileValues,
} from "./profile";
import { useSession, type SessionMe } from "./session";

const STATUSES = ["discovered", "shortlisted", "apply_ready", "applied", "outreach_ready", "rejected", "closed_withdrawn"];
const TRACKS = [
  { id: "discovery", label: "Discovery", help: "Find and shortlist jobs. Never Easy Apply." },
  { id: "application", label: "Application", help: "Submit from an apply packet and log proof." },
  { id: "outreach", label: "Outreach", help: "Email with resume PDF + short LinkedIn notes." },
  { id: "maintenance", label: "Maintenance", help: "Skill registry, proctor queue, catalog." },
] as const;
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
type InviteRow = {
  id: string;
  track: string;
  mode?: string;
  revoked_at?: string | null;
  redemptions?: number;
  max_redemptions?: number;
  allow_multiple_owners?: boolean;
  expires_at?: string;
};
type AgentRow = { id: string; display_name?: string; track?: string; kind?: string };
type SkillRow = { id: string; slug?: string; name?: string; tags?: string[]; status?: string; scope?: string };
type McpRow = { id: string; slug?: string; name?: string; kind?: string; status?: string; source?: string };
type CandidateStatus = {
  onboarded?: boolean;
  resume_present?: boolean;
  ready_for_agents?: boolean;
  missing?: string;
  present?: boolean;
};

function loginPath(next: string | null | undefined) {
  const path = next && next.startsWith("/") && !next.startsWith("//") ? next : "/board";
  return `/login?next=${encodeURIComponent(path)}`;
}

function errMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

function isCandidateRequired(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 409) return false;
  const data = err.data;
  if (!data || typeof data !== "object") return false;
  const detail = (data as { detail?: unknown }).detail;
  if (detail && typeof detail === "object" && (detail as { code?: string }).code === "candidate_required") {
    return true;
  }
  return err.message.includes("candidate_required") || err.message.includes("Onboard the candidate");
}

export function Gate({ children }: { children: (me: SessionMe) => ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.status === "loading") return <p className="page-loading">Checking session…</p>;
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
  return <p id={id} className="who-line">Signed in as {name} · {role}</p>;
}

function Shell({ me, who = "who", narrow, children }: { me?: SessionMe; who?: string; narrow?: boolean; children: ReactNode }) {
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
      <div className={narrow ? "stage stage-narrow" : "stage"}>
        {me ? <Who me={me} id={who} /> : null}
        {children}
      </div>
    </div>
  );
}

function CandidateGateBanner({ status }: { status: CandidateStatus | null }) {
  if (!status || status.onboarded) return null;
  return (
    <div className="banner warn" role="status">
      <strong>Candidate profile required.</strong>
      <span> Finish onboarding before the board, invites, skills, or agents will work.</span>
      {" "}
      <Link className="text-link" to="/onboarding">Open onboarding</Link>
      {status.missing ? <p className="muted small">Still missing: {status.missing}</p> : null}
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
      setError(errMessage(err));
    }
  }

  return (
    <Shell narrow>
      <form className="stack card-panel" onSubmit={submit}>
        <h2>Log in</h2>
        <p className="muted">Same account for the board, invites, and agent keys.</p>
        <label>
          Username or email
          <input id="username" placeholder="you@company.com" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label>
          Password
          <input id="password" placeholder="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
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
  if (session.status === "loading" || boot === null) return <p className="page-loading">Checking session…</p>;
  if (session.status === "in") return <Navigate to="/onboarding" replace />;
  if (boot) return <Navigate to="/login" replace />;
  return <Login />;
}

function Field({
  id,
  labelKey,
  value,
  onChange,
  area,
  hint,
  placeholder,
}: {
  id: string;
  labelKey: ProfileKey;
  value: string;
  onChange: (key: ProfileKey, value: string) => void;
  area?: boolean;
  hint?: string;
  placeholder?: string;
}) {
  const label = LABELS[labelKey as Exclude<ProfileKey, "revision">] || labelKey;
  const common = {
    id,
    value: value || "",
    placeholder,
    onChange: (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(labelKey, e.target.value),
  };
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {area ? <textarea {...common} /> : <input {...common} />}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

function TimezoneField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const zones = useMemo(() => allTimezones(), []);
  const [query, setQuery] = useState("");
  const selected = value || systemTimezone();
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return zones;
    return zones.filter((zone) => zone.toLowerCase().includes(q));
  }, [zones, query]);

  return (
    <label className="field">
      <span className="field-label">Timezone</span>
      <input
        type="search"
        value={query}
        placeholder="Search timezones…"
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search timezones"
      />
      <select
        id="timezone"
        value={selected}
        onChange={(e) => onChange(e.target.value)}
      >
        {!filtered.some((zone) => zone === selected) ? (
          <option value={selected}>{selected === systemTimezone() ? `${selected} (system)` : selected}</option>
        ) : null}
        {filtered.map((zone) => (
          <option key={zone} value={zone}>
            {zone === systemTimezone() ? `${zone} (system)` : zone}
          </option>
        ))}
      </select>
      <span className="field-hint">{HINTS.timezone} Selected: {selected}.</span>
    </label>
  );
}

export function Onboarding({ me }: { me: SessionMe }) {
  const navigate = useNavigate();
  const [values, setValues] = useState<ProfileValues>(() => {
    const base = emptyProfile();
    base.timezone = systemTimezone();
    return base;
  });
  const [savedSnapshot, setSavedSnapshot] = useState(() => JSON.stringify(emptyProfile()));
  const [step, setStep] = useState(1);
  const [editAll, setEditAll] = useState(false);
  const [offerResume, setOfferResume] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [loaded, setLoaded] = useState(false);
  const dirty = JSON.stringify(values) !== savedSnapshot;

  useEffect(() => {
    api<{ yaml?: string }>("/api/candidate").then((data) => {
      if (data.yaml) {
        const next = fromYaml(data.yaml);
        if (!next.timezone) next.timezone = systemTimezone();
        setValues(next);
        setSavedSnapshot(JSON.stringify(next));
        setEditAll(true);
        setStep(1);
      } else {
        const draft = emptyProfile();
        draft.timezone = systemTimezone();
        setSavedSnapshot(JSON.stringify(draft));
      }
      setLoaded(true);
    }).catch((err) => {
      setError(errMessage(err));
      setLoaded(true);
    });
  }, []);

  function set(id: ProfileKey, value: string) {
    setValues((prev) => ({ ...prev, [id]: value }));
  }

  function goStep(n: number) {
    if (n === 4 && dirty) {
      setError("Save your edits before opening Resume.");
      return;
    }
    if (editAll || n <= step || (n === 4 && !dirty)) {
      setError("");
      setStep(n);
    }
  }

  function advance(from: number) {
    if (from === 1 && (!values.full_name.trim() || !values.email.trim())) {
      setError("Full name and email are required");
      return;
    }
    if (from === 2 && (!values.titles.trim() || !values.locations.trim())) {
      setError("A title and a target location are required");
      return;
    }
    setError("");
    setStep(from + 1);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!values.full_name.trim() || !values.email.trim() || !values.titles.trim() || !values.locations.trim()) {
      setError("Name, email, a title, and a target location are required");
      return;
    }
    const nextValues = {
      ...values,
      timezone: values.timezone || systemTimezone(),
      revision: String(Number(values.revision || "0") + 1),
    };
    try {
      await api("/api/candidate", { method: "PUT", body: toYaml(nextValues), headers: { "Content-Type": "text/yaml" } });
      setValues(nextValues);
      setSavedSnapshot(JSON.stringify(nextValues));
      setNote("Profile saved. Upload a resume PDF so outreach can attach it.");
      setOfferResume(true);
      setStep(4);
      setEditAll(false);
    } catch (err) {
      setError(errMessage(err));
    }
  }

  async function upload() {
    const input = document.getElementById("resume") as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) {
      setError("Choose a resume PDF");
      return;
    }
    try {
      const bytes = await file.arrayBuffer();
      await api("/api/candidate/resume", { method: "PUT", body: bytes, headers: { "Content-Type": "application/pdf" } });
      navigate("/board");
    } catch (err) {
      setError(errMessage(err));
    }
  }

  function renderStepFields(which: number, ids: readonly ProfileKey[]) {
    return (
      <div id={`step${which}`} className="step-panel">
        {ids.map((id) => {
          if (id === "timezone") {
            return <TimezoneField key={id} value={values.timezone} onChange={(v) => set("timezone", v)} />;
          }
          const htmlId = id === "locations" ? "locations_t" : id;
          const hintKey = id as Exclude<ProfileKey, "revision">;
          return (
            <Field
              key={id}
              id={htmlId}
              labelKey={id}
              value={values[id] || ""}
              onChange={set}
              area={id === "must_haves" || id === "deal_breakers" || id === "highlights"}
              hint={HINTS[hintKey]}
              placeholder={HINTS[hintKey]}
            />
          );
        })}
      </div>
    );
  }

  const reviewing = step === 4;
  const rev = values.revision && values.revision !== "0"
    ? `Saved · revision ${values.revision}`
    : "Draft — not saved yet";

  return (
    <Shell me={me} narrow>
      <form id="formPanel" className="stack wide card-panel" onSubmit={save}>
        <div className="onboard-head">
          <h2>Candidate onboarding</h2>
          <p id="revLine" className="status">{rev}</p>
          <p className="muted">Agents refuse to invent a profile. Fill what is true; skip what you do not know.</p>
        </div>

        <ol className="stepper" aria-label="Onboarding steps">
          {STEP_META.map((item) => (
            <li key={item.n} className={step === item.n ? "active" : step > item.n ? "done" : ""}>
              <button type="button" onClick={() => goStep(item.n)}>
                <span className="step-n">{item.n}</span>
                <span>
                  <strong>{item.title}</strong>
                  <em>{item.blurb}</em>
                </span>
              </button>
            </li>
          ))}
        </ol>

        {!loaded ? <p className="muted">Loading profile…</p> : null}

        {editAll && !reviewing ? (
          <p className="banner info">
            Existing profile loaded. Edit any step, then save on Proof.
            {" "}
            <button type="button" className="quiet" onClick={() => { setEditAll(false); setStep(1); }}>
              Restart guided flow
            </button>
          </p>
        ) : null}

        {(editAll || step === 1) && !reviewing ? renderStepFields(1, STEP1) : null}
        {(editAll || step === 2) && !reviewing ? renderStepFields(2, STEP2) : null}
        {(editAll || step === 3) && !reviewing ? renderStepFields(3, STEP3) : null}

        {(reviewing || offerResume) && !dirty ? (
          <div id="step4" className="step-panel">
            <p>Profile is saved. Add a resume PDF (stored in Hub object storage / S3 when configured) or open the board.</p>
            <label className="field">
              <span className="field-label">Resume PDF</span>
              <input id="resume" type="file" accept="application/pdf" />
              <span className="field-hint">Outreach emails attach this file. LinkedIn DMs cannot.</span>
            </label>
            <div className="row">
              <button id="uploadResume" type="button" onClick={upload}>Upload resume</button>
              <button id="skipResume" type="button" className="quiet" onClick={() => navigate("/board")}>Skip for now</button>
            </div>
          </div>
        ) : null}
        {reviewing && dirty ? (
          <div className="banner warn">
            <p>You have unsaved edits. Save the profile before uploading a resume or opening the board.</p>
            <button id="save" type="submit">Save profile</button>
          </div>
        ) : null}

        <p id="ok" className="live">{note}</p>
        <p id="err" className="error">{error}</p>

        <div className="row actions">
          {!reviewing && step > 1 && !editAll ? (
            <button type="button" className="quiet" id={`back${step - 1}`} onClick={() => setStep(step - 1)}>Back</button>
          ) : null}
          {!reviewing && !editAll && step === 1 ? <button id="to2" type="button" onClick={() => advance(1)}>Continue</button> : null}
          {!reviewing && !editAll && step === 2 ? <button id="to3" type="button" onClick={() => advance(2)}>Continue</button> : null}
          {!reviewing && (editAll || step === 3) ? <button id="save" type="submit">Save profile</button> : null}
        </div>
      </form>
    </Shell>
  );
}

export function Home({ me }: { me: SessionMe }) {
  return (
    <Shell me={me} who="whoLabel" narrow>
      <div className="card-panel">
        <h2>Home</h2>
        <p className="muted">Open the board once the candidate profile is saved.</p>
        <p><Link className="button" to="/board">Open board</Link></p>
      </div>
    </Shell>
  );
}

export function Board({ me }: { me: SessionMe }) {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<JobDraft | null>(null);
  const [side, setSide] = useState("");
  const [error, setError] = useState("");
  const [needsCandidate, setNeedsCandidate] = useState(false);
  const [cand, setCand] = useState<CandidateStatus | null>(null);
  const [pausing, setPausing] = useState(false);
  const [pauseReason, setPauseReason] = useState("");

  async function load(query = q): Promise<JobRow[]> {
    const data = await api<{ jobs?: JobRow[] }>(`/api/jobs?q=${encodeURIComponent(query)}`);
    setJobs(data.jobs || []);
    setNeedsCandidate(false);
    return data.jobs || [];
  }

  useEffect(() => {
    api<CandidateStatus>("/api/candidate/status").then(setCand).catch(() => {});
    load("").catch((err) => {
      if (isCandidateRequired(err)) {
        setNeedsCandidate(true);
        setError("Onboard the candidate profile before the board can load jobs.");
        return;
      }
      setError(errMessage(err));
    });
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
      <CandidateGateBanner status={cand} />
      {needsCandidate ? (
        <div className="card-panel empty-state">
          <h2>Board is waiting on onboarding</h2>
          <p className="muted">Jobs and live streams return <code>409 candidate_required</code> until the profile has a name, email, title, and location.</p>
          <button type="button" onClick={() => navigate("/onboarding")}>Go to onboarding</button>
          {error ? <p className="error">{error}</p> : null}
        </div>
      ) : (
        <>
          <div className="row toolbar">
            <input id="q" value={q} placeholder="Search company or title" onChange={(e) => setQ(e.target.value)} />
            <button id="refresh" type="button" onClick={() => load(q).catch((err) => setError(errMessage(err)))}>Refresh</button>
          </div>
          {error ? <p className="error">{error}</p> : null}
          {!jobs.length ? (
            <div className="empty-state">
              <p className="muted">No jobs yet. Discovery agents write rows here after you mint a discovery invite.</p>
              <Link className="button quiet" to="/admin">Create invite</Link>
            </div>
          ) : null}
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
              <form className="stack card-panel" onSubmit={save}>
                <label>Company<input id="f_company" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
                <label>Title<input id="f_title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
                <label>Notes<textarea id="f_notes" value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} /></label>
                <label>Status
                  <select id="f_status" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>
                    {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                </label>
                <label>Rejection by
                  <select id="f_rejection_by" value={draft.rejection_by} onChange={(e) => setDraft({ ...draft, rejection_by: e.target.value })}>
                    <option value="">—</option>
                    <option value="company">company</option>
                    <option value="user">user</option>
                  </select>
                </label>
                <label>Company remarks<textarea id="f_company_remarks" value={draft.company_remarks} onChange={(e) => setDraft({ ...draft, company_remarks: e.target.value })} /></label>
                <label>Your remarks<textarea id="f_user_remarks" value={draft.user_remarks} onChange={(e) => setDraft({ ...draft, user_remarks: e.target.value })} /></label>
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
        </>
      )}
    </Shell>
  );
}

const INVITE_MODES = [
  { id: "owner_then_agents", label: "Owner then agents", help: "First join on an empty track becomes the owner; later joins are agents." },
  { id: "owner_only", label: "Owner only", help: "Every redemption is a track owner. Needs multi-owner if the track already has one." },
  { id: "agents_only", label: "Agents only", help: "All redemptions are agents. An owner must already exist or be minted another way." },
] as const;

export function Invites({ me }: { me: SessionMe }) {
  const navigate = useNavigate();
  const [track, setTrack] = useState("discovery");
  const [mode, setMode] = useState<(typeof INVITE_MODES)[number]["id"]>("owner_then_agents");
  const [maxRedemptions, setMaxRedemptions] = useState(5);
  const [ttlHours, setTtlHours] = useState(72);
  const [allowMultiple, setAllowMultiple] = useState(false);
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [fresh, setFresh] = useState<{ join_url: string; token?: string } | null>(null);
  const [error, setError] = useState("");
  const [needsCandidate, setNeedsCandidate] = useState(false);
  const [cand, setCand] = useState<CandidateStatus | null>(null);

  async function load() {
    const data = await api<{ invites?: InviteRow[] }>("/api/invites");
    setInvites(data.invites || []);
    setNeedsCandidate(false);
  }

  useEffect(() => {
    api<CandidateStatus>("/api/candidate/status").then(setCand).catch(() => {});
    load().catch((err) => {
      if (isCandidateRequired(err)) {
        setNeedsCandidate(true);
        setError("Onboard the candidate before minting invites.");
        return;
      }
      setError(errMessage(err));
    });
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const data = await api<{ join_url: string; token?: string }>("/api/invites", {
        method: "POST",
        body: JSON.stringify({
          track,
          mode,
          max_redemptions: maxRedemptions,
          ttl_hours: ttlHours,
          allow_multiple_owners: allowMultiple,
        }),
      });
      setFresh(data);
      await load();
    } catch (err) {
      if (isCandidateRequired(err)) {
        setNeedsCandidate(true);
        setError("Onboard the candidate before minting invites.");
        return;
      }
      setError(errMessage(err));
    }
  }

  async function revoke(id: string) {
    await api(`/api/invites/${id}/revoke`, { method: "POST", body: "{}" });
    await load();
  }

  const trackMeta = TRACKS.find((item) => item.id === track) || TRACKS[0];
  const modeMeta = INVITE_MODES.find((item) => item.id === mode) || INVITE_MODES[0];
  const prompt = fresh
    ? `Join ${fresh.join_url} and read AGENTS.md before you search. Review the packet before any apply.`
    : "Create an invite. Share the join URL once — the secret is shown only here.";

  return (
    <Shell me={me} narrow>
      <CandidateGateBanner status={cand} />
      <div className="card-panel">
        <h2>Invites</h2>
        <p id="soon" className="muted">Mint a track invite for an agent. Review and resume tailoring stay operator-owned.</p>
        {needsCandidate ? (
          <div className="empty-state">
            <p className="error">{error}</p>
            <button type="button" onClick={() => navigate("/onboarding")}>Go to onboarding</button>
          </div>
        ) : (
          <>
            <form id="form" className="stack" onSubmit={create}>
              <label>
                Track
                <select id="track" value={track} onChange={(e) => setTrack(e.target.value)}>
                  {TRACKS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
                <span className="field-hint">{trackMeta.help}</span>
              </label>
              <label>
                Mode
                <select id="mode" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                  {INVITE_MODES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
                <span className="field-hint">{modeMeta.help}</span>
              </label>
              <div className="row">
                <label>
                  Max redemptions
                  <input type="number" min={1} max={50} value={maxRedemptions} onChange={(e) => setMaxRedemptions(Number(e.target.value) || 1)} />
                </label>
                <label>
                  TTL (hours)
                  <input type="number" min={1} max={720} value={ttlHours} onChange={(e) => setTtlHours(Number(e.target.value) || 1)} />
                </label>
              </div>
              <label className="check">
                <input type="checkbox" checked={allowMultiple} onChange={(e) => setAllowMultiple(e.target.checked)} />
                Allow multiple owners on this track
              </label>
              <span className="field-hint">Needed for a second owner_only invite when the track already has an owner. Does not turn later owner_then_agents joins into owners.</span>
              <button type="submit">Create invite</button>
            </form>
            {fresh ? (
              <p id="created" className="banner info">
                Join URL (shown once): <span id="url" className="mono">{fresh.join_url}</span>
              </p>
            ) : null}
            <textarea id="prompt" readOnly value={prompt} />
            {error ? <p className="error">{error}</p> : null}
            <table id="rows">
              <thead>
                <tr><th>Track</th><th>Uses</th><th>Owners</th><th /></tr>
              </thead>
              <tbody>
                {invites.map((inv) => (
                  <tr key={inv.id}>
                    <td>{inv.track}</td>
                    <td>{inv.revoked_at ? "revoked" : `${inv.redemptions ?? 0}/${inv.max_redemptions ?? 0}`}</td>
                    <td>{inv.allow_multiple_owners ? "multi" : "single"}</td>
                    <td>{inv.revoked_at ? null : <button type="button" className="quiet" onClick={() => revoke(inv.id)}>Revoke</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!invites.length ? <p className="muted">No invites yet.</p> : null}
          </>
        )}
      </div>
    </Shell>
  );
}

export function Users({ me }: { me: SessionMe }) {
  const [users, setUsers] = useState<AgentRow[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ users?: AgentRow[] }>("/api/agents").then((data) => setUsers(data.users || [])).catch((err) => setError(errMessage(err)));
  }, []);
  return (
    <Shell me={me} narrow>
      <div className="card-panel">
        <h2>Agents</h2>
        {error ? <p className="error">{error}</p> : null}
        <table id="rows">
          <tbody>
            {users.map((user) => (
              <tr key={user.id}><td>{user.display_name}</td><td>{user.track}</td><td>{user.kind}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}

export function Skills({ me }: { me: SessionMe }) {
  const navigate = useNavigate();
  const [tag, setTag] = useState("");
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [mcps, setMcps] = useState<McpRow[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [needsCandidate, setNeedsCandidate] = useState(false);
  const [cand, setCand] = useState<CandidateStatus | null>(null);

  async function load(next = tag) {
    const [skillData, mcpData] = await Promise.all([
      api<{ skills?: SkillRow[] }>(`/api/registry/skills${next ? `?tag=${encodeURIComponent(next)}` : ""}`),
      api<{ mcps?: McpRow[] }>("/api/registry/mcps"),
    ]);
    setSkills(skillData.skills || []);
    setMcps(mcpData.mcps || []);
    setNeedsCandidate(false);
    setError("");
  }

  useEffect(() => {
    api<CandidateStatus>("/api/candidate/status").then(setCand).catch(() => {});
    load("").catch((err) => {
      if (isCandidateRequired(err)) {
        setNeedsCandidate(true);
        setError("Onboard the candidate before the skill registry opens.");
        return;
      }
      setError(errMessage(err));
    });
  }, []);

  async function seed() {
    try {
      const data = await api<{ seeded?: number }>("/api/registry/seed", { method: "POST", body: "{}" });
      setMsg(`Seeded ${data.seeded ?? 0} registry rows`);
      await load(tag);
    } catch (err) {
      setError(errMessage(err));
    }
  }

  return (
    <Shell me={me}>
      <CandidateGateBanner status={cand} />
      <div className="card-panel">
        <h2>Skills & MCPs</h2>
        <p className="muted">Shared starters agents load by tag. Seed once after a fresh Hub, then filter.</p>
        {needsCandidate ? (
          <div className="empty-state">
            <p className="error">{error}</p>
            <button type="button" onClick={() => navigate("/onboarding")}>Go to onboarding</button>
          </div>
        ) : (
          <>
            <div className="row toolbar">
              <select id="tag" value={tag} onChange={(e) => setTag(e.target.value)}>
                <option value="">all</option>
                <option value="source">source</option>
                <option value="apply">apply</option>
                <option value="outreach">outreach</option>
                <option value="research">research</option>
                <option value="maintain">maintain</option>
              </select>
              <button id="reload" type="button" onClick={() => load(tag).catch((err) => setError(errMessage(err)))}>Reload</button>
              <button id="seed" type="button" onClick={seed}>Seed</button>
            </div>
            <p id="msg" className="live">{msg}</p>
            {error ? <p className="error">{error}</p> : null}
            <h3>Skills</h3>
            <ul id="skills" className="registry-list">
              {skills.map((skill) => (
                <li key={skill.id}>
                  <strong>{skill.slug || skill.name}</strong>
                  <span className="muted"> {skill.scope || "shared"} · {skill.status || "approved"}</span>
                  <div className="tag-row">{(skill.tags || []).map((t) => <span key={t} className="tag">{t}</span>)}</div>
                </li>
              ))}
            </ul>
            {!skills.length ? <p className="muted">No skills yet. Click Seed.</p> : null}
            <h3>MCPs</h3>
            <ul id="mcps" className="registry-list">
              {mcps.map((mcp) => (
                <li key={mcp.id}>
                  <strong>{mcp.slug || mcp.name || mcp.id}</strong>
                  <span className="muted"> {mcp.kind || "mcp"} · {mcp.status || "adopted"}</span>
                  {mcp.source ? <div className="mono small">{mcp.source}</div> : null}
                </li>
              ))}
            </ul>
            {!mcps.length ? <p className="muted">No MCPs yet. Seed loads mcp.example.json when the Hub repo root is set.</p> : null}
          </>
        )}
      </div>
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
  const [error, setError] = useState("");

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
    }).catch((err) => setError(errMessage(err)));
  }, []);

  async function load(next = filter) {
    const data = await api<{ items?: MemoryItem[] }>(`/api/memory/items${next ? `?pod=${encodeURIComponent(next)}` : ""}`);
    setItems(data.items || []);
  }
  useEffect(() => { load("").catch((err) => setError(errMessage(err))); }, []);

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
    <Shell me={me} narrow>
      <div className="card-panel">
        <h2>Memory</h2>
        <p className="muted">Durable facts only — portal quirks, blockers, dead tools. No transcripts or secrets.</p>
        {error ? <p className="error">{error}</p> : null}
        <form className="stack wide" onSubmit={add}>
          <label>Pod
            <select id="write-pod" value={pod} onChange={(e) => { setPod(e.target.value); setKind(KINDS[scopeOf(e.target.value)][0]); }}>
              {pods.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>Kind
            <select id="write-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>Title<input id="write-title" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <label>Body<textarea id="write-body" value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <div className="row">
            <button id="add-item" type="submit">Add</button>
            {editing ? <button id="save-item" type="button" onClick={save}>Save</button> : null}
          </div>
          <p id="compose-status">{status}</p>
        </form>
        <div className="row toolbar">
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
      </div>
    </Shell>
  );
}

export function Data({ me }: { me: SessionMe }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "jobs";
  const [rows, setRows] = useState<string[]>([]);
  const [stats, setStats] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let gone = false;
    async function run() {
      setError("");
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
    run().catch((err) => { if (!gone) setError(errMessage(err)); });
    return () => { gone = true; };
  }, [tab]);

  function pick(next: string) {
    setParams({ tab: next });
  }

  return (
    <Shell me={me}>
      <div className="card-panel">
        <div className="row">
          {["jobs", "people", "candidate", "skills", "mcps", "memory"].map((name) => (
            <button key={name} type="button" data-tab={name} className={tab === name ? undefined : "quiet"} onClick={() => pick(name)}>{name}</button>
          ))}
        </div>
        <p id="stats">{stats}</p>
        {error ? <p className="error">{error}</p> : null}
        <table id="table"><tbody>{rows.map((row, index) => <tr key={index}><td>{row}</td></tr>)}</tbody></table>
      </div>
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
      setError(errMessage(err));
    }
  }

  return (
    <Shell narrow>
      <form id="form" className="stack card-panel" onSubmit={submit}>
        <h2>Join {id}</h2>
        <p className="muted">Redeem the invite secret from the operator. Your API key is shown once.</p>
        <input id="name" placeholder="bot name" value={name} onChange={(e) => setName(e.target.value)} />
        <input id="model" placeholder="model" value={model} onChange={(e) => setModel(e.target.value)} />
        <input id="harness" placeholder="harness" value={harness} onChange={(e) => setHarness(e.target.value)} />
        <input id="bed" placeholder="bed" value={bed} onChange={(e) => setBed(e.target.value)} />
        <input id="provider" placeholder="provider" value={provider} onChange={(e) => setProvider(e.target.value)} />
        <input id="capabilities" placeholder="capabilities" value={capabilities} onChange={(e) => setCapabilities(e.target.value)} />
        <button type="submit">Redeem invite</button>
        {key ? <p id="key" className="banner info">API key, shown once: <span className="mono">{key}</span></p> : null}
        {error ? <p className="error">{error}</p> : null}
      </form>
    </Shell>
  );
}
