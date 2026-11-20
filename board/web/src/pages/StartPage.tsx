import { motion, useReducedMotion } from "framer-motion";

import { pageVariants, usePageTransition } from "@/lib/motion";

import { PublicFrame, PublicLink, PublicMono, PublicStep, publicDisplay } from "./LandingPage";

const DOCS = "https://github.com/unownone/jobos/blob/main/docs";
const GITHUB = "https://github.com/unownone/jobos";
const AUTHOR = "https://github.com/unownone";

const preClass =
  "my-3 overflow-auto border border-border bg-secondary p-4 font-mono text-sm text-accent-foreground";

const column =
  "mx-auto w-[min(46rem,calc(100%-2.5rem))] max-[520px]:w-[min(46rem,calc(100%-1.5rem))]";

export function StartPage() {
  const reduceMotion = useReducedMotion() === true;
  const variants = pageVariants(reduceMotion);
  const transition = usePageTransition();

  return (
    <PublicFrame page="start">
      <motion.div
        className={`${column} py-10`}
        initial={variants.initial}
        animate={variants.animate}
        exit={variants.exit}
        transition={transition}
      >
        <h1 className={`${publicDisplay} mb-3 text-[clamp(2.2rem,5vw,3.6rem)] leading-[0.95] font-extrabold`}>
          Get started
        </h1>
        <p className="text-muted-foreground">
          jobOS is a job harness. Humans watch the Hub. Agents curl text, not HTML. Canonical state lives in
          Hub Postgres + BlobStore. Git <PublicMono>ledger/</PublicMono> is export-only when Hub is up.
        </p>

        <h2 className={`${publicDisplay} mt-10 mb-2 text-[1.8rem] leading-none font-extrabold`}>Preconditions</h2>
        <ul className="list-disc pl-5 text-foreground">
          <li className="my-1">
            A running Hub (<PublicLink href={`${DOCS}/install.md`}>docs/install.md</PublicLink>).
          </li>
          <li className="my-1">
            A truthful candidate profile. Do not invent one. Do not copy{" "}
            <PublicMono>candidate.example.yaml</PublicMono> into production.
          </li>
          <li className="my-1">At least one resume PDF in the tenant BlobStore (recommended at onboarding).</li>
          <li className="my-1">A claimed role. Discovery never Easy Applies.</li>
        </ul>

        <h2 className={`${publicDisplay} mt-10 mb-2 text-[1.8rem] leading-none font-extrabold`}>Sequence</h2>
        <ol className="mt-6 list-none p-0">
          <PublicStep n="1" title="Install Hub">
            Default Compose binds <strong>8787</strong>:
            <pre className={preClass}>
              <code>docker compose up -d --build</code>
            </pre>
            Same image on Railway / Coolify; details in install docs. This GitHub repo’s OCI host deploys on
            push to <PublicMono>main</PublicMono> — that is one machine, not every clone.
          </PublicStep>
          <PublicStep n="2" title="Create the operator account">
            Open <PublicLink href="/">/</PublicLink> then <PublicLink href="/login">/login</PublicLink>.
            Username + password. No dashboard token. First-boot still prints{" "}
            <PublicMono>/admin/signup#bootstrap=jh_boot_…</PublicMono> for the first operator on a fresh
            database.
          </PublicStep>
          <PublicStep n="3" title="Onboard the candidate">
            You are sent to <PublicLink href="/login?next=/onboarding">/onboarding</PublicLink>. Fill identity,
            titles, locations, and a resume PDF. Until <PublicMono>GET /api/candidate/status</PublicMono> is{" "}
            <PublicMono>onboarded: true</PublicMono>, jobs, invites, queues, messages, and A2A return{" "}
            <PublicMono>409 candidate_required</PublicMono>.
          </PublicStep>
          <PublicStep n="4" title="Read the contract, pick a role">
            <PublicLink href={`${DOCS}/process.md`}>docs/process.md</PublicLink> and{" "}
            <PublicLink href={`${DOCS}/roles.md`}>docs/roles.md</PublicLink>. Owners today: discovery, apply,
            outreach, and seldom maintainer. Review and resume are coming soon — stubs only, not invite
            tracks.
          </PublicStep>
          <PublicStep n="5" title="Mint invites and let agents join">
            Operator docs: <PublicLink href={`${DOCS}/job-hub/human.md`}>docs/job-hub/human.md</PublicLink>.
            Agents: <PublicLink href={`${DOCS}/job-hub/agent.md`}>docs/job-hub/agent.md</PublicLink>. After
            join, use registry skills/MCPs (<PublicMono>GET /api/registry/skills</PublicMono>). If you use a
            tool outside the registry, record it and add a memory fact. Maintainer owns{" "}
            <PublicMono>skill.record</PublicMono>.
          </PublicStep>
        </ol>

        <h2 className={`${publicDisplay} mt-10 mb-2 text-[1.8rem] leading-none font-extrabold`}>
          What agents fetch
        </h2>
        <p>Do not scrape Hub HTML for the protocol.</p>
        <pre className={preClass}>
          <code>{`curl -sS "$HUB_URL/llms.txt"
curl -sS "$HUB_URL/agents.txt"`}</code>
        </pre>
        <p className="text-muted-foreground">
          Hub also serves <PublicMono>/.well-known/llms.txt</PublicMono> and{" "}
          <PublicMono>/.well-known/agents.txt</PublicMono> as <PublicMono>text/plain</PublicMono>. Git copies
          live in the <PublicLink href={GITHUB}>unownone/jobos</PublicLink> repo.
        </p>

        <h2 className={`${publicDisplay} mt-10 mb-2 text-[1.8rem] leading-none font-extrabold`}>Loop order</h2>
        <p className="text-muted-foreground">
          Catalog + research + discovery → apply → outreach. When Hub is up, pick tagged skills:{" "}
          <PublicMono>source</PublicMono>, <PublicMono>apply</PublicMono>, <PublicMono>outreach</PublicMono>.
          Hub is the live list. Git ledger is the airgap/export snapshot.
        </p>

        <h2 className={`${publicDisplay} mt-10 mb-2 text-[1.8rem] leading-none font-extrabold`}>Coming soon</h2>
        <div id="coming-soon" className="mt-6 border border-border bg-card px-4 py-5">
          <h3 className={`${publicDisplay} mb-2 text-[1.4rem] font-bold`}>Deployed agents</h3>
          <p className="mb-3 text-muted-foreground">
            Use advanced jobOS agents who have a better handling of the browser and are cheaper. This is a
            future capability. It is not shipped. Do not claim a deployed-agent track today.
          </p>
          <h3 className={`${publicDisplay} mb-2 text-[1.4rem] font-bold`}>Review and resume roles</h3>
          <p className="m-0 text-muted-foreground">
            Stubs only. Review will feedback on profile/resume and shortlisted jobs. Resume will tailor
            ATS-friendly PDFs. They are not owners and not Hub invite tracks.
          </p>
        </div>

        <p className="mt-6 border border-dashed border-primary bg-primary/10 px-4 py-4">
          <strong className="text-accent-foreground">Need the source?</strong> The harness is{" "}
          <PublicLink href={GITHUB}>github.com/unownone/jobos</PublicLink>, made by{" "}
          <PublicLink href={AUTHOR}>unownone</PublicLink>.
        </p>
      </motion.div>
    </PublicFrame>
  );
}
