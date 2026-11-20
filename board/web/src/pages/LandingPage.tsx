import { useEffect, type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { pageMotion, usePageTransition } from "@/lib/motion";

const GITHUB = "https://github.com/unownone/jobos";
const AUTHOR = "https://github.com/unownone";
const DOCS = "https://github.com/unownone/jobos/blob/main/docs";

export const publicDisplay =
  "font-display tracking-[-0.03em] [font-family:var(--font-display)]";

const wrap =
  "mx-auto w-[min(72rem,calc(100%-2.5rem))] max-[520px]:w-[min(72rem,calc(100%-1.5rem))]";

const navLink =
  "inline-flex min-h-11 items-center px-0.5 font-medium text-foreground no-underline hover:text-accent-foreground aria-[current=page]:text-primary";

const sectionTitle = `${publicDisplay} mb-3 text-[clamp(1.8rem,3.4vw,2.6rem)] leading-none font-extrabold`;

type PublicPage = "landing" | "start";

function sectionHref(page: PublicPage, id: "capabilities" | "loop"): string {
  switch (page) {
    case "landing":
      return `#${id}`;
    case "start":
      return `/#${id}`;
    default: {
      const exhaustive: never = page;
      return exhaustive;
    }
  }
}

function scrollPublicHash(behavior: ScrollBehavior) {
  const id = window.location.hash.slice(1);
  if (!id) return;
  const main = document.getElementById("main");
  const target = document.getElementById(id);
  if (!main || !target || !main.contains(target)) return;
  const top = target.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
  main.scrollTo({ top, behavior });
}

function currentPage(page: PublicPage): "page" | undefined {
  switch (page) {
    case "landing":
      return undefined;
    case "start":
      return "page";
    default: {
      const exhaustive: never = page;
      return exhaustive;
    }
  }
}

export function PublicMono({ children }: { children: ReactNode }) {
  return <code className="font-mono text-[0.9em] break-words">{children}</code>;
}

export function PublicLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      className="text-accent-foreground underline-offset-[0.18em] hover:text-foreground hover:underline"
    >
      {children}
    </a>
  );
}

export function PublicStep({
  n,
  title,
  children,
}: {
  n: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="grid grid-cols-[2.6rem_minmax(0,1fr)] gap-3 border-b border-border py-4">
      <span className={`${publicDisplay} text-[1.6rem] leading-none font-bold text-primary`}>{n}</span>
      <div>
        <strong className="mb-1 block">{title}</strong>
        {children}
      </div>
    </li>
  );
}

export function PublicFrame({ page, children }: { page: PublicPage; children: ReactNode }) {
  const reduceMotion = useReducedMotion() === true;

  useEffect(() => {
    const behavior: ScrollBehavior = reduceMotion ? "auto" : "smooth";
    const scroll = () => scrollPublicHash(behavior);
    scroll();
    window.addEventListener("hashchange", scroll);
    return () => window.removeEventListener("hashchange", scroll);
  }, [reduceMotion]);

  return (
    <div className="relative flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-[radial-gradient(700px_280px_at_80%_0%,color-mix(in_srgb,var(--primary)_16%,transparent),transparent_60%)]"
      />
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-40 focus:m-2 focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <header className="relative z-10 flex shrink-0 items-center justify-between gap-4 border-b border-border bg-background px-5 py-2.5 pl-[max(1.25rem,env(safe-area-inset-left))] pr-[max(1.25rem,env(safe-area-inset-right))] max-[520px]:flex-col max-[520px]:items-start">
        <a href="/" className="flex min-h-11 items-center gap-3 text-foreground no-underline">
          <span className="grid size-10 shrink-0 place-items-center overflow-hidden">
            <img
              src="/brand/mascot.png"
              width={40}
              height={40}
              alt=""
              className="size-[4.6rem] max-w-none object-cover"
            />
          </span>
          <span className={`${publicDisplay} text-[1.7rem] leading-none font-extrabold`}>
            job<span className="text-primary">OS</span>
          </span>
        </a>
        <nav
          aria-label="Primary"
          className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 max-[520px]:w-full max-[520px]:justify-start"
        >
          <a href={sectionHref(page, "capabilities")} className={navLink}>
            Capabilities
          </a>
          <a href={sectionHref(page, "loop")} className={navLink}>
            Loop
          </a>
          <a href="/start" aria-current={currentPage(page)} className={navLink}>
            Get started
          </a>
          <a href={GITHUB} className={navLink}>
            GitHub
          </a>
          <Button asChild className="ml-1 shrink-0">
            <a href="/login">Log in</a>
          </Button>
        </nav>
      </header>
      <main id="main" className="relative z-10 min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        {children}
        <footer
          className={`${wrap} mt-12 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-border py-5 pb-[calc(1.5rem+env(safe-area-inset-bottom))] text-[0.95rem] text-muted-foreground`}
        >
          <div>
            <a href={GITHUB} className="text-foreground no-underline hover:text-accent-foreground">
              github.com/unownone/jobos
            </a>
            {" · MIT"}
          </div>
          <div>
            made by{" "}
            <a href={AUTHOR} className="font-semibold text-foreground no-underline hover:text-accent-foreground">
              unownone
            </a>
          </div>
        </footer>
      </main>
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <Badge variant="outline" className="mx-0.5 align-middle font-mono text-[0.75rem] text-accent-foreground">
      {children}
    </Badge>
  );
}

function Spec({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 border-b border-border py-4 min-[881px]:grid-cols-[minmax(9rem,12.5rem)_minmax(0,1fr)]">
      <dt className={`${publicDisplay} m-0 text-[1.35rem] leading-none font-bold text-primary`}>{title}</dt>
      <dd className="m-0 max-w-[60ch]">{children}</dd>
    </div>
  );
}

function LoopStep({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <li className="relative border-b border-border px-4 py-5 last:border-b-0 min-[881px]:border-r min-[881px]:border-b-0 min-[881px]:last:border-r-0">
      <span className="mb-1 block font-mono text-xs text-muted-foreground">{n}</span>
      <h3 className={`${publicDisplay} mb-2 text-[1.45rem] leading-none font-bold`}>{title}</h3>
      <p className="m-0 text-sm text-muted-foreground">{children}</p>
    </li>
  );
}

export function LandingPage() {
  const reduceMotion = useReducedMotion() === true;
  const transition = usePageTransition();

  return (
    <PublicFrame page="landing">
      <motion.div
        className={`${wrap} grid grid-cols-1 items-center gap-10 py-12 max-[880px]:pt-7 min-[881px]:grid-cols-[minmax(0,1.15fr)_minmax(16rem,0.85fr)] min-[881px]:gap-x-12`}
        initial={reduceMotion ? false : pageMotion.initial}
        animate={reduceMotion ? { opacity: 1 } : pageMotion.animate}
        exit={reduceMotion ? { opacity: 0 } : pageMotion.exit}
        transition={transition}
      >
        <div>
          <h1
            className={`${publicDisplay} mb-3 max-w-[14ch] text-balance text-[clamp(2.6rem,7vw,5.4rem)] leading-[0.92] font-extrabold max-[880px]:max-w-[12ch]`}
          >
            Find jobs with a harness, not a spreadsheet.
          </h1>
          <p className="mb-6 max-w-[38rem] text-[1.12rem] text-muted-foreground">
            jobOS is a job harness. Catalog, research, and discovery shortlist the work. Apply submits
            from a packet. Outreach follows by email and LinkedIn DM. Live state lives in Hub. Git{" "}
            <PublicMono>ledger/</PublicMono> is export and airgap — not a second board.
          </p>
          <p className="flex flex-wrap gap-3">
            <Button asChild>
              <a href="/login">Log in or create an account</a>
            </Button>
            <Button asChild variant="secondary" className="border border-border">
              <a href="/start">Get started</a>
            </Button>
          </p>
        </div>
        <aside
          aria-label="Agent entry console"
          className="relative min-h-[22rem] overflow-hidden border border-border bg-card max-[880px]:min-h-0"
        >
          <span aria-hidden="true" className="absolute top-2.5 left-2.5 size-1.5 rounded-full border border-primary opacity-70" />
          <span aria-hidden="true" className="absolute top-2.5 right-2.5 size-1.5 rounded-full border border-primary opacity-70" />
          <img
            src="/brand/mascot.png"
            width={320}
            height={320}
            alt="jobOS beetle mascot"
            className="h-60 w-full object-cover object-[52%_46%]"
          />
          <div className="mx-4 mb-4 border-t border-dashed border-primary bg-secondary px-4 py-3 font-mono text-[0.82rem] leading-relaxed text-accent-foreground">
            <div>
              <span className="text-primary">$</span> <code>curl -sS "$HUB_URL/llms.txt"</code>
            </div>
            <div>
              <span className="text-primary">$</span> <code>curl -sS "$HUB_URL/agents.txt"</code>
            </div>
          </div>
        </aside>
      </motion.div>

      <section id="capabilities" className={`${wrap} pt-12`}>
        <h2 className={sectionTitle}>What it can do</h2>
        <p className="max-w-[65ch] text-muted-foreground">
          Capabilities from the process, not a marketplace pitch. Discovery never Easy Applies.
        </p>
        <dl className="mt-7 border-t border-border">
          <Spec title="Discovery">
            Source, enrich, score, and shortlist. Write a complete apply packet. No form submit. No Easy
            Apply.
          </Spec>
          <Spec title="Deep research">
            Company, people, role, and portal research. A shared tool the owners call — not a fourth hunt
            bot.
          </Spec>
          <Spec title="Apply">
            Claim <PublicMono>apply_ready</PublicMono> work, submit from the packet, write something worth
            reading, log proof. Blocked portals stay blocked.
          </Spec>
          <Spec title="Outreach">
            Email with the resume PDF attached, plus LinkedIn DMs asking for a short chat. Default channels
            only. No SMS, WhatsApp, or InMail sequences.
          </Spec>
          <Spec title="Catalog + registry">
            Discover and vet skills and MCPs. Hub live selection is <PublicMono>GET /api/registry/skills</PublicMono>{" "}
            tagged <Tag>source</Tag>
            <Tag>apply</Tag>
            <Tag>outreach</Tag>. Git lists remain inventory.
          </Spec>
          <Spec title="Hub + ledger">
            Hub JobStore (Postgres) + BlobStore + RabbitMQ is the live list.{" "}
            <PublicMono>GET /api/export/ledger</PublicMono> writes YAML when you need files. Do not dual-write.
          </Spec>
          <Spec title="Roles">
            Three hunt owners — discovery, apply, outreach — plus maintainer (seldom): skill lists, Hub
            registry proctor, hunt board. Review and resume are stubs. Do not claim them.
          </Spec>
        </dl>
      </section>

      <section id="loop" className={`${wrap} pt-12`}>
        <h2 className={sectionTitle}>The loop</h2>
        <p className="max-w-[65ch] text-muted-foreground">
          Catalog + research + discovery, then apply, then outreach. Maintainer is a fourth owner and is
          seldom used. Nobody jumps the queue.
        </p>
        <div className="mt-6 border border-border bg-card/70">
          <div className="flex flex-wrap justify-between gap-4 border-b border-dashed border-primary px-4 py-3 font-mono text-xs tracking-[0.04em] text-muted-foreground uppercase">
            <span>Hunt loop</span>
            <span>Maintainer ≠ discovery</span>
          </div>
          <ol id="loop-rail" className="m-0 grid list-none grid-cols-1 p-0 min-[881px]:grid-cols-5">
            <LoopStep n="1" title="Catalog">
              Vet skills and MCPs. Write the stack the workspace can actually use.
            </LoopStep>
            <LoopStep n="2" title="Research">
              Deep research on the company, team, and portal. Shared across lanes.
            </LoopStep>
            <LoopStep n="3" title="Discovery">
              Shortlist + apply packet. Tagged <PublicMono>source</PublicMono> skills. Never Easy Apply.
            </LoopStep>
            <LoopStep n="4" title="Apply">
              Submit from the packet. Tagged <PublicMono>apply</PublicMono> skills (ATS / site).
            </LoopStep>
            <LoopStep n="5" title="Outreach">
              Email + LinkedIn DM after apply, or when there is no portal.
            </LoopStep>
          </ol>
          <div className="grid grid-cols-1 border-t border-border min-[881px]:grid-cols-2">
            <article className="p-4 min-[881px]:border-r min-[881px]:border-border">
              <h3 className={`${publicDisplay} mb-1 text-[1.2rem] font-bold`}>Maintainer (seldom)</h3>
              <p className="m-0 text-[0.95rem] text-muted-foreground">
                Owns <PublicMono>skills/lists/</PublicMono>, seeds and proctors the Hub skill registry, keeps
                the board up. Does not source jobs, apply, or send mail.
              </p>
            </article>
            <article className="border-t border-border p-4 min-[881px]:border-t-0">
              <h3 className={`${publicDisplay} mb-1 text-[1.2rem] font-bold`}>Registry tags</h3>
              <p className="m-0 text-[0.95rem] text-muted-foreground">
                When Hub is up, pick a matching tagged skill: <PublicMono>?tag=source</PublicMono>,{" "}
                <PublicMono>?tag=apply</PublicMono>, <PublicMono>?tag=outreach</PublicMono>. Airgap falls back
                to role <PublicMono>SKILL.md</PublicMono> plus starters. Do not load another bot’s local skill.
              </p>
            </article>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-1 gap-px border border-border bg-border min-[881px]:grid-cols-2">
          <article className="bg-background p-4">
            <h3 className={`${publicDisplay} mb-1 text-[1.35rem] font-bold`}>Hub JobStore (live)</h3>
            <p className="m-0 text-muted-foreground">
              Canonical jobs, events, people, skills, memory, and queue traffic. Sign up at{" "}
              <PublicLink href="/login">/login</PublicLink>. Board is{" "}
              <PublicLink href="/login?next=/board">/board</PublicLink> after a truthful candidate profile
              exists.
            </p>
          </article>
          <article className="bg-background p-4">
            <h3 className={`${publicDisplay} mb-1 text-[1.35rem] font-bold`}>git ledger/ (airgap export)</h3>
            <p className="m-0 text-muted-foreground">
              Not the live list when Hub is up. Export with <PublicMono>GET /api/export/ledger</PublicMono>.
              Airgapped bots still write YAML locally. Never dual-write.
            </p>
          </article>
        </div>
      </section>

      <section id="start" className={`${wrap} pt-12`}>
        <h2 className={sectionTitle}>Get started</h2>
        <p className="max-w-[65ch] text-muted-foreground">
          Onboard a truthful candidate before anything else. Do not invent one. Do not ship the example
          profile as live data.
        </p>
        <ol className="mt-6 list-none p-0">
          <PublicStep n="1" title="Install Hub">
            Compose on port 8787, or see <PublicLink href={`${DOCS}/install.md`}>docs/install.md</PublicLink>.
            Agents curl <PublicMono>llms.txt</PublicMono> / <PublicMono>agents.txt</PublicMono> — they do not
            scrape HTML.
          </PublicStep>
          <PublicStep n="2" title="Create an account">
            Username + password at <PublicLink href="/login">/login</PublicLink>. No dashboard token. First
            boot still uses the printed <PublicMono>/admin/signup</PublicMono> bootstrap URL.
          </PublicStep>
          <PublicStep n="3" title="Onboard the candidate">
            <PublicLink href="/login?next=/onboarding">/onboarding</PublicLink> is mandatory: identity, titles,
            locations, resume PDF. Until then the Hub returns <PublicMono>409 candidate_required</PublicMono>.
            Jobs, invites, and A2A stay closed.
          </PublicStep>
          <PublicStep n="4" title="Claim a role and join workers">
            Read <PublicLink href={`${DOCS}/process.md`}>docs/process.md</PublicLink> and{" "}
            <PublicLink href={`${DOCS}/roles.md`}>docs/roles.md</PublicLink>. Mint track invites. Agents join,
            heartbeat, and claim tenant-namespaced work.
          </PublicStep>
          <PublicStep n="5" title="Run the loop in order">
            Discovery first (catalog → research → shortlist). Then apply. Then outreach. Maintainer is not a
            hunt lane.
          </PublicStep>
        </ol>
        <p className="mt-6 border border-dashed border-primary bg-primary/10 px-4 py-4">
          <strong className="text-accent-foreground">Blocked until onboarding.</strong> Missing candidate.yaml
          / Hub onboarding is a hard stop — not a skip. Full sequence: <PublicLink href="/start">Get started</PublicLink>.
        </p>
      </section>
    </PublicFrame>
  );
}
