import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import logo from "./assets/brand/logo.png";
import mascot from "./assets/brand/mascot.png";
import { useSession } from "./session";

const GITHUB = "https://github.com/unownone/jobos";
const AUTHOR = "https://github.com/unownone";
const DOCS = "https://github.com/unownone/jobos/blob/main/docs";

function Mono({ children }: { children: ReactNode }) {
  return <code className="mono">{children}</code>;
}

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} className="text-link">
      {children}
    </a>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}

function PublicChrome({ page, children }: { page: "landing" | "start"; children: ReactNode }) {
  const session = useSession();
  const signedIn = session.status === "in";
  const accountHref = signedIn ? "/board" : "/login";
  const accountLabel = signedIn ? "Open board" : "Log in";

  return (
    <div className="public-shell" data-page={page}>
      <div className="public-glow" aria-hidden="true" />
      <a href="#main" className="skip">
        Skip to content
      </a>
      <header className="public-top">
        <Link to="/" className="brand">
          <span className="brand-mark">
            <img src={logo} width="40" height="40" alt="" />
          </span>
          <span className="brand-name">
            job<span className="accent">OS</span>
          </span>
        </Link>
        <nav aria-label="Primary" className="public-nav">
          <a href={page === "landing" ? "#capabilities" : "/#capabilities"}>Capabilities</a>
          <a href={page === "landing" ? "#loop" : "/#loop"}>Loop</a>
          <Link to="/start" aria-current={page === "start" ? "page" : undefined}>
            Get started
          </Link>
          <a href={GITHUB}>GitHub</a>
          <Link className="button" to={accountHref}>
            {accountLabel}
          </Link>
        </nav>
      </header>
      <main id="main" className="public-main">
        {children}
        <footer className="public-foot">
          <div>
            <a href={GITHUB}>github.com/unownone/jobos</a> · MIT
          </div>
          <div>
            made by <a href={AUTHOR}>unownone</a>
          </div>
        </footer>
      </main>
    </div>
  );
}

function Spec({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="spec">
      <dt>{title}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function LoopStep({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <li>
      <span className="loop-n">{n}</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </li>
  );
}

function Step({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <li className="step">
      <span>{n}</span>
      <div>
        <strong>{title}</strong>
        <div>{children}</div>
      </div>
    </li>
  );
}

export function Landing() {
  const session = useSession();
  const signedIn = session.status === "in";

  return (
    <PublicChrome page="landing">
      <section className="hero-grid">
        <div>
          <h1>Find jobs with a harness, not a spreadsheet.</h1>
          <p className="lede">
            jobOS is a job harness. Catalog, research, and discovery shortlist the work. Apply submits from a
            packet. Outreach follows by email and LinkedIn DM. Live state lives in Hub. Git <Mono>ledger/</Mono>{" "}
            is export and airgap — not a second board.
          </p>
          <p className="row">
            <Link className="button" to={signedIn ? "/board" : "/login"}>
              {signedIn ? "Open board" : "Log in or create an account"}
            </Link>
            <Link className="button quiet" to="/start">
              Get started
            </Link>
          </p>
        </div>
        <aside className="console" aria-label="Agent entry console">
          <img src={mascot} width="320" height="320" alt="jobOS beetle mascot" />
          <div className="console-panel">
            <div>
              <span className="accent">$</span> <code>curl -sS &quot;$HUB_URL/llms.txt&quot;</code>
            </div>
            <div>
              <span className="accent">$</span> <code>curl -sS &quot;$HUB_URL/agents.txt&quot;</code>
            </div>
          </div>
        </aside>
      </section>

      <section id="capabilities" className="public-section">
        <h2>What it can do</h2>
        <p className="muted">Capabilities from the process, not a marketplace pitch. Discovery never Easy Applies.</p>
        <dl className="specs">
          <Spec title="Discovery">
            Source, enrich, score, and shortlist. Write a complete apply packet. No form submit. No Easy Apply.
          </Spec>
          <Spec title="Deep research">
            Company, people, role, and portal research. A shared tool the owners call — not a fourth hunt bot.
          </Spec>
          <Spec title="Apply">
            Claim <Mono>apply_ready</Mono> work, submit from the packet, write something worth reading, log proof.
            Blocked portals stay blocked.
          </Spec>
          <Spec title="Outreach">
            Email with the resume PDF attached, plus LinkedIn DMs asking for a short chat. Default channels only. No
            SMS, WhatsApp, or InMail sequences.
          </Spec>
          <Spec title="Catalog + registry">
            Discover and vet skills and MCPs. Hub live selection is <Mono>GET /api/registry/skills</Mono> tagged{" "}
            <Tag>source</Tag>
            <Tag>apply</Tag>
            <Tag>outreach</Tag>. Git lists remain inventory.
          </Spec>
          <Spec title="Hub + ledger">
            Hub JobStore (Postgres) + BlobStore is the live list. <Mono>GET /api/export/ledger</Mono> writes YAML when
            you need files. Do not dual-write.
          </Spec>
          <Spec title="Roles">
            Three hunt owners — discovery, apply, outreach — plus maintainer (seldom): skill lists, Hub registry
            proctor, hunt board. Review and resume are stubs. Do not claim them.
          </Spec>
        </dl>
      </section>

      <section id="loop" className="public-section">
        <h2>The loop</h2>
        <p className="muted">
          Catalog + research + discovery, then apply, then outreach. Maintainer is a fourth owner and is seldom used.
          Nobody jumps the queue.
        </p>
        <div className="loop-card">
          <div className="loop-head">
            <span>Hunt loop</span>
            <span>Maintainer ≠ discovery</span>
          </div>
          <ol className="loop-rail">
            <LoopStep n="1" title="Catalog">
              Vet skills and MCPs. Write the stack the workspace can actually use.
            </LoopStep>
            <LoopStep n="2" title="Research">
              Deep research on the company, team, and portal. Shared across lanes.
            </LoopStep>
            <LoopStep n="3" title="Discovery">
              Shortlist + apply packet. Tagged <Mono>source</Mono> skills. Never Easy Apply.
            </LoopStep>
            <LoopStep n="4" title="Apply">
              Submit from the packet. Tagged <Mono>apply</Mono> skills (ATS / site).
            </LoopStep>
            <LoopStep n="5" title="Outreach">
              Email + LinkedIn DM after apply, or when there is no portal.
            </LoopStep>
          </ol>
          <div className="loop-notes">
            <article>
              <h3>Maintainer (seldom)</h3>
              <p>
                Owns <Mono>skills/lists/</Mono>, seeds and proctors the Hub skill registry, keeps the board up. Does
                not source jobs, apply, or send mail.
              </p>
            </article>
            <article>
              <h3>Registry tags</h3>
              <p>
                When Hub is up, pick a matching tagged skill: <Mono>?tag=source</Mono>, <Mono>?tag=apply</Mono>,{" "}
                <Mono>?tag=outreach</Mono>. Airgap falls back to role <Mono>SKILL.md</Mono> plus starters.
              </p>
            </article>
          </div>
        </div>
        <div className="store-grid">
          <article>
            <h3>Hub JobStore (live)</h3>
            <p>
              Canonical jobs, events, people, skills, memory, and queue traffic. Sign up at{" "}
              <Link className="text-link" to="/login">
                /login
              </Link>
              . Board is{" "}
              <Link className="text-link" to="/login?next=/board">
                /board
              </Link>{" "}
              after a truthful candidate profile exists.
            </p>
          </article>
          <article>
            <h3>git ledger/ (airgap export)</h3>
            <p>
              Not the live list when Hub is up. Export with <Mono>GET /api/export/ledger</Mono>. Airgapped bots still
              write YAML locally. Never dual-write.
            </p>
          </article>
        </div>
      </section>

      <section id="start" className="public-section">
        <h2>Get started</h2>
        <p className="muted">
          Onboard a truthful candidate before anything else. Do not invent one. Do not ship the example profile as live
          data.
        </p>
        <ol className="steps">
          <Step n="1" title="Install Hub">
            Compose on port 8787, or see <Ext href={`${DOCS}/install.md`}>docs/install.md</Ext>. Agents curl{" "}
            <Mono>llms.txt</Mono> / <Mono>agents.txt</Mono> — they do not scrape HTML.
          </Step>
          <Step n="2" title="Create an account">
            Username + password at{" "}
            <Link className="text-link" to="/login">
              /login
            </Link>
            . No dashboard token. First boot still uses the printed <Mono>/admin/signup</Mono> bootstrap URL.
          </Step>
          <Step n="3" title="Onboard the candidate">
            <Link className="text-link" to="/login?next=/onboarding">
              /onboarding
            </Link>{" "}
            is mandatory: identity, titles, locations, resume PDF. Until then the Hub returns{" "}
            <Mono>409 candidate_required</Mono>.
          </Step>
          <Step n="4" title="Claim a role and join workers">
            Read <Ext href={`${DOCS}/process.md`}>docs/process.md</Ext> and{" "}
            <Ext href={`${DOCS}/roles.md`}>docs/roles.md</Ext>. Mint track invites. Agents join, heartbeat, and claim
            tenant-namespaced work.
          </Step>
          <Step n="5" title="Run the loop in order">
            Discovery first (catalog → research → shortlist). Then apply. Then outreach. Maintainer is not a hunt lane.
          </Step>
        </ol>
        <p className="callout">
          <strong>Blocked until onboarding.</strong> Missing candidate onboarding is a hard stop — not a skip. Full
          sequence:{" "}
          <Link className="text-link" to="/start">
            Get started
          </Link>
          .
        </p>
      </section>
    </PublicChrome>
  );
}

export function Start() {
  return (
    <PublicChrome page="start">
      <section className="public-section start-column">
        <h1 className="start-title">Get started</h1>
        <p className="muted">
          jobOS is a job harness. Humans watch the Hub. Agents curl text, not HTML. Canonical state lives in Hub
          Postgres + BlobStore. Git <Mono>ledger/</Mono> is export-only when Hub is up.
        </p>

        <h2>Preconditions</h2>
        <ul className="bullets">
          <li>
            A running Hub (<Ext href={`${DOCS}/install.md`}>docs/install.md</Ext>).
          </li>
          <li>
            A truthful candidate profile. Do not invent one. Do not copy <Mono>candidate.example.yaml</Mono> into
            production.
          </li>
          <li>At least one resume PDF in the tenant BlobStore (recommended at onboarding).</li>
          <li>A claimed role. Discovery never Easy Applies.</li>
        </ul>

        <h2>Sequence</h2>
        <ol className="steps">
          <Step n="1" title="Install Hub">
            Default Compose binds <strong>8787</strong>:
            <pre className="pre">
              <code>docker compose up -d --build</code>
            </pre>
          </Step>
          <Step n="2" title="Create the operator account">
            Open{" "}
            <Link className="text-link" to="/login">
              /login
            </Link>
            . Username + password. First-boot still prints <Mono>/admin/signup#bootstrap=jh_boot_…</Mono> on a fresh
            database.
          </Step>
          <Step n="3" title="Onboard the candidate">
            Fill identity, titles, locations, and a resume PDF on{" "}
            <Link className="text-link" to="/login?next=/onboarding">
              /onboarding
            </Link>
            . Until onboarded, jobs and invites return <Mono>409 candidate_required</Mono>. A2A{" "}
            <Mono>message/send</Mono> returns JSON-RPC error <Mono>-32090</Mono>.
          </Step>
          <Step n="4" title="Read the contract, pick a role">
            <Ext href={`${DOCS}/process.md`}>docs/process.md</Ext> and{" "}
            <Ext href={`${DOCS}/roles.md`}>docs/roles.md</Ext>.
          </Step>
          <Step n="5" title="Mint invites and let agents join">
            Operator docs: <Ext href={`${DOCS}/job-hub/human.md`}>docs/job-hub/human.md</Ext>. Agents:{" "}
            <Ext href={`${DOCS}/job-hub/agent.md`}>docs/job-hub/agent.md</Ext>.
          </Step>
        </ol>

        <h2>What agents fetch</h2>
        <p>Do not scrape Hub HTML for the protocol.</p>
        <pre className="pre">
          <code>{`curl -sS "$HUB_URL/llms.txt"
curl -sS "$HUB_URL/agents.txt"`}</code>
        </pre>

        <p className="callout">
          <strong>Need the source?</strong> The harness is <Ext href={GITHUB}>github.com/unownone/jobos</Ext>, made by{" "}
          <Ext href={AUTHOR}>unownone</Ext>.
        </p>
      </section>
    </PublicChrome>
  );
}
