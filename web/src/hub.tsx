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

/** Writable statuses offered in the job editor (common lane transitions). */
const STATUSES = ["discovered", "shortlisted", "apply_ready", "applied", "outreach_ready", "rejected", "closed_withdrawn"];
/** Full server status set for board filtering (see server/internal/httpapi/domain.go). */
const FILTER_STATUSES = [
  "discovered", "enriching", "shortlisted", "skipped", "apply_ready", "applying", "applied",
  "apply_blocked", "outreach_ready", "outreaching", "waiting", "chatting", "interview", "offer",
  "rejected", "closed_expired", "closed_rejected", "closed_withdrawn",
];
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
  url?: string;
  apply_url?: string;
  location?: string;
  updated_at?: string;
  rejection?: JobRejection | null;
};
type JobDraft = {
  company: string;
  title: string;
  notes: string;
  status: string;
  url: string;
  apply_url: string;
  rejection_by: string;
  company_remarks: string;
  user_remarks: string;
};
type BoardSortKey = "company" | "title" | "status" | "updated";
type BoardPageSize = 10 | 20;

function jobLink(job: Pick<JobRow, "url" | "apply_url">): string {
  return (job.apply_url || job.url || "").trim();
}

function jobStatusKey(job: JobRow): string {
  return job.stopped ? "stopped" : (job.status || "discovered");
}
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
type McpClientSnippet = {
  id: string;
  label: string;
  format?: string;
  filename?: string;
  config: string;
  instruction?: string;
};
type FreshInvite = {
  join_url: string;
  token?: string;
  api_key?: string;
  mcp_url?: string;
  mcp_clients?: McpClientSnippet[];
  auth_hint?: string;
  mcp_bootstrap_error?: string;
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
  const location = useLocation();
  const links = [
    { to: "/board", label: "Board" },
    { to: "/onboarding", label: "Onboarding" },
    { to: "/admin", label: "Invites", exact: true },
    { to: "/admin/skills", label: "Skills" },
    { to: "/admin/memory", label: "Memory" },
  ] as const;
  return (
    <div className="shell">
      <header className="top">
        <Link to="/board" className="brand-lockup">
          <h1>job<span className="accent">OS</span></h1>
        </Link>
        <nav>
          {links.map((link) => {
            const active = "exact" in link && link.exact
              ? location.pathname === link.to
              : location.pathname === link.to || location.pathname.startsWith(`${link.to}/`);
            return (
              <Link key={link.to} to={link.to} className={active ? "nav-active" : undefined} aria-current={active ? "page" : undefined}>
                {link.label}
              </Link>
            );
          })}
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

function countByStatus(jobs: JobRow[]): { key: string; label: string; count: number }[] {
  const buckets = [
    { key: "discovered", label: "Found" },
    { key: "shortlisted", label: "Shortlist" },
    { key: "apply_ready", label: "Apply ready" },
    { key: "applied", label: "Applied" },
    { key: "outreach_ready", label: "Outreach" },
    { key: "rejected", label: "Rejected" },
  ];
  return buckets.map((bucket) => ({
    ...bucket,
    count: jobs.filter((job) => (job.stopped ? "stopped" : job.status || "") === bucket.key).length,
  }));
}

function statusTone(status: string): string {
  switch (status) {
    case "applied":
    case "outreach_ready":
      return "tone-good";
    case "rejected":
    case "closed_withdrawn":
    case "stopped":
      return "tone-bad";
    case "shortlisted":
    case "apply_ready":
      return "tone-hot";
    default:
      return "tone-muted";
  }
}

export function Board({ me }: { me: SessionMe }) {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [pausedFilter, setPausedFilter] = useState<"all" | "active" | "paused">("all");
  const [sortKey, setSortKey] = useState<BoardSortKey>("updated");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [pageSize, setPageSize] = useState<BoardPageSize>(10);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<JobDraft | null>(null);
  const [side, setSide] = useState("");
  const [error, setError] = useState("");
  const [needsCandidate, setNeedsCandidate] = useState(false);
  const [cand, setCand] = useState<CandidateStatus | null>(null);
  const [pausing, setPausing] = useState(false);
  const [pauseReason, setPauseReason] = useState("");
  const [live, setLive] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const statusCounts = useMemo(() => countByStatus(jobs), [jobs]);
  const stoppedCount = useMemo(() => jobs.filter((job) => job.stopped).length, [jobs]);

  const filteredJobs = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let rows = jobs.filter((job) => {
      const status = jobStatusKey(job);
      if (statusFilter !== "all" && status !== statusFilter) return false;
      if (pausedFilter === "paused" && !job.stopped) return false;
      if (pausedFilter === "active" && job.stopped) return false;
      if (!needle) return true;
      const hay = `${job.company || ""} ${job.title || ""} ${job.location || ""} ${job.url || ""} ${job.apply_url || ""}`.toLowerCase();
      return hay.includes(needle);
    });
    const dir = sortDir === "asc" ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      const av = (() => {
        switch (sortKey) {
          case "company":
            return (a.company || "").toLowerCase();
          case "title":
            return (a.title || "").toLowerCase();
          case "status":
            return jobStatusKey(a);
          case "updated":
            return a.updated_at || a.id;
          default: {
            const _exhaustive: never = sortKey;
            return _exhaustive;
          }
        }
      })();
      const bv = (() => {
        switch (sortKey) {
          case "company":
            return (b.company || "").toLowerCase();
          case "title":
            return (b.title || "").toLowerCase();
          case "status":
            return jobStatusKey(b);
          case "updated":
            return b.updated_at || b.id;
          default: {
            const _exhaustive: never = sortKey;
            return _exhaustive;
          }
        }
      })();
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return (a.company || "").localeCompare(b.company || "") * dir;
    });
    return rows;
  }, [jobs, q, statusFilter, pausedFilter, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(filteredJobs.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  useEffect(() => {
    if (page !== currentPage) setPage(currentPage);
  }, [page, currentPage]);
  const pageJobs = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredJobs.slice(start, start + pageSize);
  }, [filteredJobs, currentPage, pageSize]);
  const filterStatusOptions = useMemo(() => {
    const extras = jobs
      .map((job) => jobStatusKey(job))
      .filter((status) => status !== "stopped" && !FILTER_STATUSES.includes(status));
    return [...FILTER_STATUSES, ...Array.from(new Set(extras))];
  }, [jobs]);

  async function load(): Promise<JobRow[]> {
    const data = await api<{ jobs?: JobRow[] }>("/api/jobs");
    setJobs(data.jobs || []);
    setNeedsCandidate(false);
    setLoaded(true);
    return data.jobs || [];
  }

  useEffect(() => {
    setPage(1);
  }, [q, statusFilter, pausedFilter, sortKey, sortDir, pageSize]);

  useEffect(() => {
    api<CandidateStatus>("/api/candidate/status").then(setCand).catch(() => {});
    load().catch((err) => {
      setLoaded(true);
      if (isCandidateRequired(err)) {
        setNeedsCandidate(true);
        setError("Onboard the candidate profile before the board can load jobs.");
        return;
      }
      setError(errMessage(err));
    });
    const source = new EventSource("/api/stream", { withCredentials: true });
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    source.onmessage = () => {
      setLive(true);
      load().catch(() => {});
    };
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
      url: job.url || "",
      apply_url: job.apply_url || "",
      rejection_by: rejection.by || "",
      company_remarks: rejection.company_remarks || "",
      user_remarks: rejection.user_remarks || "",
    });
    setSide("");
  }

  function toggleSort(key: BoardSortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir(key === "updated" ? "desc" : "asc");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !selected) return;
    const body: Record<string, unknown> = {
      company: draft.company,
      title: draft.title,
      notes: draft.notes,
      status: draft.status,
      url: draft.url,
      apply_url: draft.apply_url,
    };
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
        <div className="card-panel empty-state board-gate">
          <p className="eyebrow">Hunt board</p>
          <h2>Finish onboarding first</h2>
          <p className="muted">Jobs and live streams stay locked until the candidate has a name, email, title, and location.</p>
          <button type="button" onClick={() => navigate("/onboarding")}>Go to onboarding</button>
          {error ? <p className="error">{error}</p> : null}
        </div>
      ) : (
        <>
          <header className="board-head">
            <div>
              <p className="eyebrow">Hunt board</p>
              <h2>Pipeline</h2>
              <p className="muted">Discovery agents land jobs here. Steer status, pause lanes, and push apply / outreach from each row.</p>
            </div>
            <div className="board-head-actions">
              <span className={`live-pill ${live ? "on" : ""}`} title={live ? "SSE connected" : "SSE reconnecting"}>
                <span className="live-dot" aria-hidden="true" />
                {live ? "Live" : "Connecting"}
              </span>
              <Link className="button" to="/admin">Mint invite</Link>
            </div>
          </header>

          <section className={`metric-strip ${jobs.length ? "" : "metric-strip-ready"}`.trim()} aria-label="Board summary">
            <div className="metric">
              <span className="metric-value">{jobs.length}</span>
              <span className="metric-label">Jobs</span>
            </div>
            {jobs.length
              ? statusCounts.filter((item) => item.count > 0).map((item) => (
                <div key={item.key} className="metric">
                  <span className="metric-value">{item.count}</span>
                  <span className="metric-label">{item.label}</span>
                </div>
              ))
              : (
                <div className="metric metric-soft metric-wide">
                  <span className="metric-value">Start discovery</span>
                  <span className="metric-label">Next step · mint an invite, then redeem from an agent</span>
                </div>
              )}
            {stoppedCount ? (
              <div className="metric">
                <span className="metric-value">{stoppedCount}</span>
                <span className="metric-label">Paused</span>
              </div>
            ) : null}
            <div className="metric metric-soft">
              <span className="metric-value">{cand?.resume_present ? "Yes" : "No"}</span>
              <span className="metric-label">Resume</span>
            </div>
            <div className="metric metric-soft" title={cand?.ready_for_agents ? "Candidate + resume ready for agents" : "Upload a resume (and finish onboarding) before agents should run"}>
              <span className="metric-value">{cand?.ready_for_agents ? "Ready" : "Wait"}</span>
              <span className="metric-label">Agent-ready</span>
            </div>
          </section>

          <div className="row toolbar board-toolbar">
            <input id="q" value={q} placeholder="Search company, title, or URL" onChange={(e) => setQ(e.target.value)} />
            <label className="board-filter">
              <span className="sr-only">Status</span>
              <select id="statusFilter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
                <option value="all">All statuses</option>
                {filterStatusOptions.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}
                <option value="stopped">paused</option>
              </select>
            </label>
            <label className="board-filter">
              <span className="sr-only">Paused</span>
              <select id="pausedFilter" value={pausedFilter} onChange={(e) => setPausedFilter(e.target.value as "all" | "active" | "paused")} aria-label="Filter paused jobs">
                <option value="all">Active + paused</option>
                <option value="active">Active only</option>
                <option value="paused">Paused only</option>
              </select>
            </label>
            <label className="board-filter">
              <span className="sr-only">Sort</span>
              <select id="sortKey" value={sortKey} onChange={(e) => setSortKey(e.target.value as BoardSortKey)} aria-label="Sort by">
                <option value="updated">Sort · updated</option>
                <option value="company">Sort · company</option>
                <option value="title">Sort · title</option>
                <option value="status">Sort · status</option>
              </select>
            </label>
            <button type="button" className="quiet" onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))} aria-label="Toggle sort direction">
              {sortDir === "asc" ? "Asc" : "Desc"}
            </button>
            <label className="board-filter">
              <span className="sr-only">Page size</span>
              <select id="pageSize" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value) as BoardPageSize)} aria-label="Rows per page">
                <option value={10}>10 / page</option>
                <option value={20}>20 / page</option>
              </select>
            </label>
            <button id="refresh" type="button" className="quiet" onClick={() => load().catch((err) => setError(errMessage(err)))}>Refresh</button>
          </div>
          {error ? <p className="error">{error}</p> : null}

          {!loaded ? (
            <p className="muted">Loading jobs…</p>
          ) : !jobs.length ? (
            <section className="board-empty" aria-label="Empty board">
              <div className="board-empty-hero card-panel">
                <h3>No jobs on the board yet</h3>
                <p className="muted">Mint a discovery invite, redeem it from an agent with a browser, and shortlisted roles show up in this list automatically.</p>
                <div className="row actions">
                  <Link className="button" to="/admin">Create discovery invite</Link>
                  <Link className="button quiet" to="/admin/skills">Review skills</Link>
                </div>
              </div>
              <div className="next-grid">
                <article className="next-card">
                  <p className="eyebrow">1 · Find</p>
                  <h4>Discovery lane</h4>
                  <p className="muted">Agents catalog openings. Never Easy Apply on this track.</p>
                  <Link className="text-link" to="/admin">Open invites</Link>
                </article>
                <article className="next-card">
                  <p className="eyebrow">2 · Submit</p>
                  <h4>Application lane</h4>
                  <p className="muted">When a row is apply_ready, send a packet and log proof here.</p>
                  <Link className="text-link" to="/onboarding">Check candidate</Link>
                </article>
                <article className="next-card">
                  <p className="eyebrow">3 · Reach out</p>
                  <h4>Outreach lane</h4>
                  <p className="muted">Email with the resume PDF; keep LinkedIn notes short.</p>
                  <Link className="text-link" to="/admin/memory">Read memory</Link>
                </article>
              </div>
            </section>
          ) : (
            <div className="split board-split">
              <div className="job-table-wrap card-panel">
                {!filteredJobs.length ? (
                  <p className="muted board-filter-empty">No jobs match these filters.</p>
                ) : (
                  <>
                    <table id="list" className="job-table">
                      <thead>
                        <tr>
                          <th><button type="button" className="th-sort" onClick={() => toggleSort("company")}>Company{sortKey === "company" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}</button></th>
                          <th><button type="button" className="th-sort" onClick={() => toggleSort("title")}>Title{sortKey === "title" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}</button></th>
                          <th>URL</th>
                          <th><button type="button" className="th-sort" onClick={() => toggleSort("status")}>Status{sortKey === "status" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}</button></th>
                        </tr>
                      </thead>
                      <tbody>
                        {pageJobs.map((job) => {
                          const status = jobStatusKey(job);
                          const link = jobLink(job);
                          return (
                            <tr key={job.id} className={selected === job.id ? "is-selected" : undefined} onClick={() => open(job)}>
                              <td>{job.company || "—"}</td>
                              <td>{job.title || "—"}</td>
                              <td className="job-url-cell">
                                {link ? (
                                  <a
                                    className="job-url-link"
                                    href={link}
                                    target="_blank"
                                    rel="noreferrer"
                                    title={link}
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    {link.replace(/^https?:\/\//, "").slice(0, 42)}{link.replace(/^https?:\/\//, "").length > 42 ? "…" : ""}
                                  </a>
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                              <td><span className={`status-pill ${statusTone(status)}`}>{status.replaceAll("_", " ")}</span></td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <div className="board-pager" aria-label="Pagination">
                      <span className="muted">
                        {filteredJobs.length} match{(filteredJobs.length === 1 ? "" : "es")} · page {currentPage} / {pageCount}
                      </span>
                      <div className="row">
                        <button type="button" className="quiet" disabled={currentPage <= 1} onClick={() => setPage(Math.max(1, currentPage - 1))}>Prev</button>
                        <button type="button" className="quiet" disabled={currentPage >= pageCount} onClick={() => setPage(Math.min(pageCount, currentPage + 1))}>Next</button>
                      </div>
                    </div>
                  </>
                )}
              </div>
              {draft ? (
                <form className="stack card-panel job-editor" onSubmit={save}>
                  <h3 className="editor-title">Edit job</h3>
                  <label>Company<input id="f_company" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
                  <label>Title<input id="f_title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
                  <label>Posting URL<input id="f_url" value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} placeholder="https://…" /></label>
                  <label>Apply URL<input id="f_apply_url" value={draft.apply_url} onChange={(e) => setDraft({ ...draft, apply_url: e.target.value })} placeholder="https://…" /></label>
                  {(draft.apply_url || draft.url) ? (
                    <p className="job-url-preview">
                      <a href={draft.apply_url || draft.url} target="_blank" rel="noreferrer">{draft.apply_url || draft.url}</a>
                    </p>
                  ) : null}
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
                    <button id="pauseBtn" type="button" className="quiet" onClick={() => setPausing(true)}>Pause</button>
                    <button id="resumeBtn" type="button" className="quiet" onClick={resume}>Resume</button>
                  </div>
                  {pausing ? (
                    <div className="row">
                      <input id="laneReason" value={pauseReason} placeholder="Why pause" onChange={(e) => setPauseReason(e.target.value)} />
                      <button id="laneConfirm" type="button" onClick={confirmPause}>Confirm pause</button>
                    </div>
                  ) : null}
                </form>
              ) : (
                <aside className="card-panel job-editor-placeholder">
                  <h3>Select a job</h3>
                  <p className="muted">Click a row to edit status, notes, pause a lane, or record a rejection.</p>
                </aside>
              )}
            </div>
          )}
        </>
      )}
    </Shell>
  );
}


function inviteHostMismatch(joinURL: string): string {
  try {
    const created = new URL(joinURL);
    const here = window.location.hostname;
    if (created.hostname === here) return "";
    if (created.hostname === "127.0.0.1" || created.hostname === "localhost") {
      return `Join link points at ${created.hostname}. Set HUB_PUBLIC_URL=https://ikr.one (or HUB_PUBLIC_HOST=ikr.one) on the API before sharing.`;
    }
    return `Join link host is ${created.hostname}, but you are on ${here}. Prefer HUB_PUBLIC_URL matching the public Hub origin.`;
  } catch {
    return "Join link is not a valid URL.";
  }
}

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch {
      return false;
    }
  }
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
  const [fresh, setFresh] = useState<FreshInvite | null>(null);
  const [error, setError] = useState("");
  const [copyNote, setCopyNote] = useState("");
  const [clientTab, setClientTab] = useState("cursor");
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
      const data = await api<FreshInvite>("/api/invites", {
        method: "POST",
        body: JSON.stringify({
          track,
          mode,
          max_redemptions: maxRedemptions,
          ttl_hours: ttlHours,
          allow_multiple_owners: allowMultiple,
          mcp_bootstrap: true,
        }),
      });
      setFresh(data);
      setClientTab(data.mcp_clients?.[0]?.id || "cursor");
      setCopyNote("");
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
  const clients = fresh?.mcp_clients || [];
  const activeClient = clients.find((item) => item.id === clientTab) || clients[0] || null;
  const prompt = fresh
    ? (fresh.api_key
      ? `Paste the ${activeClient?.label || "MCP"} config into your AI. MCP URL ${fresh.mcp_url || ""}. Auth is the long-lived Bearer API key in that block (~90 days). Call get_started, then operate only through MCP tools. Browser join ${fresh.join_url} is fallback only.`
      : `Join ${fresh.join_url} (browser fallback), then paste MCP config with the shown API key. Prefer MCP over raw HTTP.`)
    : "Create an invite. Paste an MCP client block into Cursor, Claude, Grok, or Codex — do not rely on the /join form.";
  const hostWarn = fresh ? inviteHostMismatch(fresh.join_url) : "";

  async function copyJoin() {
    if (!fresh) return;
    const ok = await copyText(fresh.join_url);
    setCopyNote(ok ? "Join URL copied (fallback). Keep the ?s= secret intact." : "Copy failed — select the URL manually.");
  }

  async function copyPrompt() {
    const ok = await copyText(prompt);
    setCopyNote(ok ? "Agent prompt copied." : "Copy failed — select the prompt manually.");
  }

  async function copyMcpConfig() {
    if (!activeClient) return;
    const ok = await copyText(activeClient.config);
    setCopyNote(ok ? `${activeClient.label} MCP config copied. Paste into that client.` : "Copy failed — select the config manually.");
  }

  async function copyApiKey() {
    if (!fresh?.api_key) return;
    const ok = await copyText(fresh.api_key);
    setCopyNote(ok ? "API key copied. Shown once — store as Bearer for /mcp." : "Copy failed.");
  }

  async function shareJoin() {
    if (!fresh) return;
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title: "jobOS MCP invite", text: prompt, url: fresh.mcp_url || fresh.join_url });
        setCopyNote("Shared. Prefer pasting the MCP config block, not only the URL.");
        return;
      } catch {
        // Fall through to clipboard when the share sheet is dismissed or unavailable.
      }
    }
    if (activeClient) {
      await copyMcpConfig();
      return;
    }
    await copyJoin();
  }

  return (
    <Shell me={me} narrow>
      <CandidateGateBanner status={cand} />
      <div className="card-panel">
        <h2>Invites</h2>
        <p id="soon" className="muted">MCP-first join: mint a track invite, then paste a client config into the agent&apos;s AI. Browser /join is fallback only.</p>
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
              <span className="field-hint">Needed for a second owner_only invite when the track already has an owner. Creating an invite burns one redemption for the MCP API key.</span>
              <button type="submit">Create MCP invite</button>
            </form>
            {fresh ? (
              <div id="created" className="banner info invite-share">
                <p className="eyebrow">Shown once — paste into your AI</p>
                <p className="muted small">{fresh.auth_hint || "Bearer API key on /mcp (~90 days). OAuth via /connect still works."}</p>
                {fresh.mcp_url ? <p>MCP URL: <span className="mono">{fresh.mcp_url}</span></p> : null}
                {fresh.api_key ? (
                  <p>API key: <span id="api-key" className="mono">{fresh.api_key}</span></p>
                ) : (
                  <p className="error">{fresh.mcp_bootstrap_error || "No MCP API key minted — use browser join, then paste a key."}</p>
                )}
                {hostWarn ? <p className="error">{hostWarn}</p> : null}
                {clients.length ? (
                  <div className="mcp-client-blocks">
                    <div className="row tabs" role="tablist" aria-label="MCP clients">
                      {clients.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          role="tab"
                          aria-selected={activeClient?.id === item.id}
                          className={activeClient?.id === item.id ? "" : "quiet"}
                          onClick={() => setClientTab(item.id)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                    {activeClient ? (
                      <>
                        <p className="field-hint">{activeClient.instruction}</p>
                        <textarea
                          id="mcp-config"
                          className="mono mcp-config"
                          readOnly
                          value={activeClient.config}
                          rows={12}
                        />
                      </>
                    ) : null}
                  </div>
                ) : null}
                <div className="row actions">
                  {activeClient ? <button type="button" onClick={copyMcpConfig}>Copy {activeClient.label} config</button> : null}
                  {fresh.api_key ? <button type="button" className="quiet" onClick={copyApiKey}>Copy API key</button> : null}
                  <button type="button" className="quiet" onClick={copyPrompt}>Copy agent prompt</button>
                  <button type="button" className="quiet" onClick={shareJoin}>Share</button>
                  <button type="button" className="quiet" onClick={copyJoin}>Copy /join URL</button>
                </div>
                {copyNote ? <p className="muted small">{copyNote}</p> : null}
                <details className="invite-fallback">
                  <summary>Browser /join fallback</summary>
                  <p className="mono small" id="url">{fresh.join_url}</p>
                </details>
              </div>
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
  const [mcpClients, setMcpClients] = useState<McpClientSnippet[]>([]);
  const [mcpURL, setMcpURL] = useState("");
  const [error, setError] = useState("");
  const [copyNote, setCopyNote] = useState("");
  const secret = new URLSearchParams(window.location.search).get("s") || "";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!secret) {
      setError("This join link is missing the secret (?s=…). Ask the operator to resend the full URL or paste an MCP config from Invites.");
      return;
    }
    try {
      const data = await api<FreshInvite & { api_key: string }>("/api/auth/join", {
        method: "POST",
        body: JSON.stringify({
          invite_id: id,
          s: secret,
          display_name: name,
          metadata: { model, harness, bed, provider, capabilities },
        }),
      });
      setKey(data.api_key);
      setMcpClients(data.mcp_clients || []);
      setMcpURL(data.mcp_url || "");
    } catch (err) {
      setError(errMessage(err));
    }
  }

  async function copyConfig(config: string, label: string) {
    const ok = await copyText(config);
    setCopyNote(ok ? `${label} MCP config copied.` : "Copy failed.");
  }

  return (
    <Shell narrow>
      <form id="form" className="stack card-panel" onSubmit={submit}>
        <h2>Join {id}</h2>
        <p className="muted">Browser fallback. Prefer pasting an MCP client block from Invites. Your API key is shown once.</p>
        {secret ? (
          <p className="banner info">Invite secret detected in the URL.</p>
        ) : (
          <p className="banner warn">Missing ?s= secret in this URL. Sharing apps often strip query params — open the original full link, or use MCP paste from Invites.</p>
        )}
        <input id="name" placeholder="bot name" value={name} onChange={(e) => setName(e.target.value)} />
        <input id="model" placeholder="model" value={model} onChange={(e) => setModel(e.target.value)} />
        <input id="harness" placeholder="harness" value={harness} onChange={(e) => setHarness(e.target.value)} />
        <input id="bed" placeholder="bed" value={bed} onChange={(e) => setBed(e.target.value)} />
        <input id="provider" placeholder="provider" value={provider} onChange={(e) => setProvider(e.target.value)} />
        <input id="capabilities" placeholder="capabilities" value={capabilities} onChange={(e) => setCapabilities(e.target.value)} />
        <button type="submit" disabled={!secret}>Redeem invite</button>
        {key ? (
          <div className="banner info invite-share">
            <p id="key">API key, shown once: <span className="mono">{key}</span></p>
            {mcpURL ? <p className="mono small">{mcpURL}</p> : null}
            {mcpClients.map((item) => (
              <div key={item.id} className="stack">
                <p className="eyebrow">{item.label}</p>
                <textarea className="mono mcp-config" readOnly value={item.config} rows={8} />
                <button type="button" className="quiet" onClick={() => copyConfig(item.config, item.label)}>Copy {item.label}</button>
              </div>
            ))}
            {copyNote ? <p className="muted small">{copyNote}</p> : null}
          </div>
        ) : null}
        {error ? <p className="error">{error}</p> : null}
      </form>
    </Shell>
  );
}
