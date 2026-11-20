import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "./api.js";

function Shell({ me, children }) {
  return (
    <div className="shell">
      <header className="top">
        <h1>jobOS</h1>
        <nav>
          <Link to="/board">Board</Link>
          <Link to="/onboarding">Onboarding</Link>
          <Link to="/admin">Invites</Link>
          {me ? <span className="muted">{me.display_name || me.role}</span> : <Link to="/login">Login</Link>}
        </nav>
      </header>
      {children}
    </div>
  );
}

function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState("login");
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setError("");
    try {
      const path = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
      await api(path, { method: "POST", body: JSON.stringify({ username, password }) });
      navigate("/board");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Shell>
      <form className="stack" onSubmit={submit}>
        <h2>{mode === "signup" ? "Create the hub" : "Log in"}</h2>
        <input placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error ? <p className="error">{error}</p> : null}
        <div className="row">
          <button type="submit">{mode === "signup" ? "Sign up" : "Log in"}</button>
          <button type="button" className="quiet" onClick={() => setMode(mode === "signup" ? "login" : "signup")}>
            {mode === "signup" ? "I already have an account" : "First time here"}
          </button>
        </div>
      </form>
    </Shell>
  );
}

function Board() {
  const [jobs, setJobs] = useState([]);
  const [live, setLive] = useState("connecting");
  const [error, setError] = useState("");

  async function load() {
    const data = await api("/api/jobs");
    setJobs(data.jobs || []);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    const source = new EventSource("/api/stream", { withCredentials: true });
    source.onopen = () => setLive("live");
    source.onerror = () => setLive("reconnecting");
    source.onmessage = () => load().catch(() => {});
    return () => source.close();
  }, []);

  return (
    <Shell me={{ role: "board" }}>
      <p className="live">stream {live}</p>
      {error ? <p className="error">{error}</p> : null}
      <table>
        <thead>
          <tr><th>Company</th><th>Title</th><th>Status</th></tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>{job.company}</td>
              <td>{job.title}</td>
              <td className="status">{job.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {jobs.length === 0 ? <p className="muted">No jobs yet. Discovery posts them to /api/jobs.</p> : null}
    </Shell>
  );
}

function Onboarding() {
  const [yaml, setYaml] = useState("name: \ntitles:\n  - \n");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api("/api/candidate").then((data) => {
      if (data.yaml) setYaml(data.yaml);
    }).catch((err) => setError(err.message));
  }, []);

  async function save(event) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/candidate", { method: "PUT", body: yaml, headers: { "Content-Type": "text/yaml" } });
      setNote("Profile saved.");
    } catch (err) {
      setError(err.message);
    }
  }

  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const bytes = await file.arrayBuffer();
    try {
      await api("/api/candidate/resume", { method: "PUT", body: bytes, headers: { "Content-Type": "application/pdf" } });
      setNote("Resume stored.");
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Shell me={{ role: "admin" }}>
      <form className="stack" onSubmit={save}>
        <h2>Candidate</h2>
        <textarea value={yaml} onChange={(e) => setYaml(e.target.value)} />
        <button type="submit">Save profile</button>
        <label className="muted">Resume PDF <input type="file" accept="application/pdf" onChange={upload} /></label>
        {note ? <p>{note}</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </form>
    </Shell>
  );
}

function Admin() {
  const [track, setTrack] = useState("discovery");
  const [invites, setInvites] = useState([]);
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    const data = await api("/api/invites");
    setInvites(data.invites || []);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function create(event) {
    event.preventDefault();
    try {
      const data = await api("/api/invites", { method: "POST", body: JSON.stringify({ track, mode: "owner_then_agents" }) });
      setFresh(data);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Shell me={{ role: "admin" }}>
      <form className="row" onSubmit={create}>
        <select value={track} onChange={(e) => setTrack(e.target.value)}>
          <option value="discovery">discovery</option>
          <option value="application">application</option>
          <option value="outreach">outreach</option>
          <option value="maintenance">maintenance</option>
        </select>
        <button type="submit">Create invite</button>
      </form>
      {fresh ? <p>Join URL (shown once): {fresh.join_url}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <ul>
        {invites.map((inv) => (
          <li key={inv.id}>{inv.track} · {inv.mode} · {inv.redemptions}/{inv.max_redemptions}</li>
        ))}
      </ul>
    </Shell>
  );
}

function Join() {
  const { id } = useParams();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const secret = new URLSearchParams(window.location.search).get("s") || "";

  async function submit(event) {
    event.preventDefault();
    try {
      const data = await api("/api/auth/join", {
        method: "POST",
        body: JSON.stringify({ invite_id: id, s: secret, display_name: name }),
      });
      setKey(data.api_key);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Shell>
      <form className="stack" onSubmit={submit}>
        <h2>Join {id}</h2>
        <input placeholder="bot name" value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit">Redeem invite</button>
        {key ? <p>API key, shown once: {key}</p> : null}
        {error ? <p className="error">{error}</p> : null}
      </form>
    </Shell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/board" replace />} />
      <Route path="/login" element={<Login />} />
      <Route path="/board" element={<Board />} />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="/join/:id" element={<Join />} />
    </Routes>
  );
}
