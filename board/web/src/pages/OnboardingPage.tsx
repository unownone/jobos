import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { AppShell } from "@/components/shell/AppShell";
import { type ShellConn } from "@/components/shell/TopBar";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { assignHref } from "@/lib/auth-post";
import { api } from "@/lib/api";
import { panelVariants, usePageTransition, usePanelPlay } from "@/lib/motion";

type Step = "step1" | "step2" | "step3" | "step4";

type Profile = {
  identity?: Record<string, string>;
  target?: {
    titles?: string[];
    locations?: string[];
    seniority?: string[];
    domains?: string[];
    remote?: string;
    must_haves?: string[];
    deal_breakers?: string[];
  };
  proof?: {
    headline?: string;
    years_experience?: number;
    stack?: string[];
    highlights?: string[];
    do_not_claim?: string[];
  };
  materials?: { writing_voice?: string };
};

async function pdfBytes(file: Blob): Promise<Uint8Array> {
  if (typeof file.arrayBuffer === "function") return new Uint8Array(await file.arrayBuffer());
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the PDF"));
    reader.readAsArrayBuffer(file);
  });
}

function splitList(raw: string): string[] {
  return raw.split(/[\n,]/).map((part) => part.trim()).filter(Boolean);
}

function joinList(values: string[] | undefined, sep: string): string {
  return (values ?? []).filter(Boolean).join(sep);
}

const STEPS: Step[] = ["step1", "step2", "step3", "step4"];

export function OnboardingPage() {
  const reduce = useReducedMotion() === true;
  const play = usePanelPlay();
  const panel = panelVariants(reduce, play);
  const transition = usePageTransition();
  const [step, setStep] = useState<Step>("step1");
  const [who, setWho] = useState("Checking session…");
  const [headerWho, setHeaderWho] = useState("");
  const [conn, setConn] = useState<ShellConn>("signing in");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [revLine, setRevLine] = useState("");
  const [resumeOk, setResumeOk] = useState("");
  const [fullName, setFullName] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [location, setLocation] = useState("");
  const [timezone, setTimezone] = useState("");
  const [workAuthorization, setWorkAuthorization] = useState("");
  const [linkedin, setLinkedin] = useState("");
  const [github, setGithub] = useState("");
  const [titles, setTitles] = useState("");
  const [locations, setLocations] = useState("");
  const [seniority, setSeniority] = useState("");
  const [domains, setDomains] = useState("");
  const [remote, setRemote] = useState("");
  const [mustHaves, setMustHaves] = useState("");
  const [dealBreakers, setDealBreakers] = useState("");
  const [headline, setHeadline] = useState("");
  const [years, setYears] = useState("0");
  const [stack, setStack] = useState("");
  const [highlights, setHighlights] = useState("");
  const [doNotClaim, setDoNotClaim] = useState("");
  const [writingVoice, setWritingVoice] = useState("");
  const [resumeFile, setResumeFile] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      let signedIn = false;
      try {
        const me = await api<{ kind?: string; role?: string; actor?: string; user?: { email?: string } }>("/api/auth/me");
        if (cancelled) return;
        if (me.kind !== "admin" && me.role !== "admin") {
          setWho("Admin session required to onboard the candidate.");
          setConn("sign in required");
          return;
        }
        signedIn = true;
        const actor = me.user?.email || me.actor || "admin";
        setHeaderWho(actor);
        setWho(`Signed in as ${actor}. Fill a real profile.`);
        setConn("signed in");
        const loaded = await api<{ profile?: Profile; revision?: string }>("/api/candidate");
        const profile = loaded.profile;
        if (cancelled || !profile) return;
        if (loaded.revision) {
          setRevLine(`revision ${loaded.revision} · Cache-Control: no-store · heartbeat returns candidate_revision`);
        }
        const identity = profile.identity ?? {};
        const target = profile.target ?? {};
        const proof = profile.proof ?? {};
        setFullName(identity.full_name ?? "");
        setPreferredName(identity.preferred_name ?? "");
        setEmail(identity.email ?? "");
        setPhone(identity.phone ?? "");
        setLocation(identity.location ?? "");
        setTimezone(identity.timezone ?? "");
        setWorkAuthorization(identity.work_authorization ?? "");
        setLinkedin(identity.linkedin_url ?? "");
        setGithub(identity.github_url ?? "");
        setTitles(joinList(target.titles, ", "));
        setLocations(joinList(target.locations, ", "));
        setSeniority(joinList(target.seniority, ", "));
        setDomains(joinList(target.domains, ", "));
        setRemote(target.remote ?? "");
        setMustHaves(joinList(target.must_haves, "\n"));
        setDealBreakers(joinList(target.deal_breakers, "\n"));
        setHeadline(proof.headline ?? "");
        setYears(String(proof.years_experience ?? 0));
        setStack(joinList(proof.stack, ", "));
        setHighlights(joinList(proof.highlights, "\n"));
        setDoNotClaim(joinList(proof.do_not_claim, "\n"));
        setWritingVoice(profile.materials?.writing_voice ?? "");
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Sign in required.";
        if (signedIn) {
          setErr(message);
          return;
        }
        setWho(message);
        setConn("sign in required");
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  function payload() {
    return {
      identity: {
        full_name: fullName,
        preferred_name: preferredName,
        email,
        phone,
        location,
        timezone,
        work_authorization: workAuthorization,
        linkedin_url: linkedin,
        github_url: github,
        portfolio_url: "",
        website: "",
      },
      target: {
        titles: splitList(titles),
        locations: splitList(locations),
        seniority: splitList(seniority),
        domains: splitList(domains),
        remote,
        salary_floor_usd: 0,
        visa_needs: false,
        company_sizes: [] as string[],
        must_haves: splitList(mustHaves),
        deal_breakers: splitList(dealBreakers),
      },
      proof: {
        headline,
        years_experience: Number(years || 0),
        stack: splitList(stack),
        highlights: splitList(highlights),
        do_not_claim: splitList(doNotClaim),
      },
      materials: {
        resume_primary: "assets/resume/resume-primary.pdf",
        resume_variants: [] as string[],
        writing_voice: writingVoice,
      },
      constraints: {
        max_discovers_per_cycle: 40,
        max_shortlist_per_cycle: 12,
        max_applies_per_day: 8,
        max_outreach_touches_per_person: 2,
        easy_apply_policy: "never during discovery; apply role may use it only after a packet exists",
      },
    };
  }

  function toTargets() {
    setErr("");
    if (!fullName.trim() || !email.trim()) {
      setErr("Full name and email are required.");
      return;
    }
    setStep("step2");
  }

  function toProof() {
    setErr("");
    if (splitList(titles).length === 0 || splitList(locations).length === 0) {
      setErr("At least one title and one location are required.");
      return;
    }
    setStep("step3");
  }

  async function save() {
    setErr("");
    setOk("");
    try {
      const body = await api<{ revision?: string }>("/api/candidate", { method: "PUT", body: payload() });
      setOk(`Profile saved. Revision ${body.revision || "updated"}. Agents must re-fetch GET /api/candidate/public (Cache-Control: no-store).`);
      setRevLine(`revision ${body.revision || ""} · Cache-Control: no-store · heartbeat returns candidate_revision`);
      setStep("step4");
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not save the profile");
    }
  }

  async function uploadResume() {
    setErr("");
    if (!resumeFile) {
      setErr("Choose a PDF first.");
      return;
    }
    try {
      const bytes = await pdfBytes(resumeFile);
      await api("/api/candidate/resume", { method: "PUT", raw: bytes, contentType: "application/pdf" });
      setResumeOk("Resume stored. Opening the board…");
      assignHref("/board");
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not store the resume");
    }
  }

  return (
    <AppShell title="Candidate onboarding" scroll="page" path="/onboarding" subtitle="A real profile. Agents must not invent one." who={headerWho} conn={conn}>
      <main id="main" className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-5">
        <p id="who" className="m-0 text-sm text-muted-foreground">{who}</p>
        <ol className="m-0 flex list-none gap-2 p-0">
          {STEPS.map((id, index) => (
            <li key={id} id={`s${index + 1}`}>
              <Button
                type="button"
                variant={step === id ? "default" : "outline"}
                aria-current={step === id ? "step" : undefined}
                className="min-w-11"
                onClick={() => setStep(id)}
              >
                {index + 1}
              </Button>
            </li>
          ))}
        </ol>
        <div id="formPanel" className="flex flex-col gap-4 border border-border bg-card p-4">
          <p id="err" className="m-0 text-sm text-destructive">{err}</p>
          <p id="ok" className="m-0 text-sm">{ok}</p>
          <p id="revLine" className="m-0 text-sm text-muted-foreground">{revLine}</p>
          {STEPS.map((id) => (
            <div key={id} id={id} hidden={step !== id}>
              <motion.div
                key={step === id ? `${id}-on` : `${id}-off`}
                initial={step === id ? panel.initial : false}
                animate={step === id ? panel.animate : { opacity: 1 }}
                transition={transition}
                className="flex flex-col gap-3"
              >
                {id === "step1" ? (
                  <>
                    <h2 className="m-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">Identity</h2>
                    <Field>Full name<Input id="full_name" value={fullName} autoComplete="name" onChange={(event) => setFullName(event.target.value)} /></Field>
                    <Field>Preferred name<Input id="preferred_name" value={preferredName} onChange={(event) => setPreferredName(event.target.value)} /></Field>
                    <Field>Email<Input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
                    <Field>Phone<Input id="phone" value={phone} onChange={(event) => setPhone(event.target.value)} /></Field>
                    <Field>Location<Input id="location" value={location} onChange={(event) => setLocation(event.target.value)} /></Field>
                    <Field>Timezone<Input id="timezone" value={timezone} onChange={(event) => setTimezone(event.target.value)} /></Field>
                    <Field>Work authorization<Input id="work_authorization" value={workAuthorization} onChange={(event) => setWorkAuthorization(event.target.value)} /></Field>
                    <Field>LinkedIn<Input id="linkedin_url" value={linkedin} onChange={(event) => setLinkedin(event.target.value)} /></Field>
                    <Field>GitHub<Input id="github_url" value={github} onChange={(event) => setGithub(event.target.value)} /></Field>
                    <Button id="to2" type="button" onClick={toTargets}>Next — targets</Button>
                  </>
                ) : null}
                {id === "step2" ? (
                  <>
                    <h2 className="m-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">Targets</h2>
                    <Field>Titles<Input id="titles" value={titles} onChange={(event) => setTitles(event.target.value)} /></Field>
                    <Field>Locations<Input id="locations_t" value={locations} onChange={(event) => setLocations(event.target.value)} /></Field>
                    <Field>Seniority<Input id="seniority" value={seniority} onChange={(event) => setSeniority(event.target.value)} /></Field>
                    <Field>Domains<Input id="domains" value={domains} onChange={(event) => setDomains(event.target.value)} /></Field>
                    <Field>Remote<Input id="remote" value={remote} onChange={(event) => setRemote(event.target.value)} /></Field>
                    <Field>Must-haves<Textarea id="must_haves" value={mustHaves} onChange={(event) => setMustHaves(event.target.value)} /></Field>
                    <Field>Deal-breakers<Textarea id="deal_breakers" value={dealBreakers} onChange={(event) => setDealBreakers(event.target.value)} /></Field>
                    <div className="flex gap-2">
                      <Button id="back1" type="button" variant="outline" onClick={() => setStep("step1")}>Back</Button>
                      <Button id="to3" type="button" onClick={toProof}>Next — proof</Button>
                    </div>
                  </>
                ) : null}
                {id === "step3" ? (
                  <>
                    <h2 className="m-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">Proof</h2>
                    <Field>Headline<Input id="headline" value={headline} onChange={(event) => setHeadline(event.target.value)} /></Field>
                    <Field>Years<Input id="years" type="number" min={0} value={years} onChange={(event) => setYears(event.target.value)} /></Field>
                    <Field>Stack<Input id="stack" value={stack} onChange={(event) => setStack(event.target.value)} /></Field>
                    <Field>Highlights<Textarea id="highlights" value={highlights} onChange={(event) => setHighlights(event.target.value)} /></Field>
                    <Field>Do not claim<Textarea id="do_not_claim" value={doNotClaim} onChange={(event) => setDoNotClaim(event.target.value)} /></Field>
                    <Field>Writing voice<Input id="writing_voice" value={writingVoice} onChange={(event) => setWritingVoice(event.target.value)} /></Field>
                    <div className="flex gap-2">
                      <Button id="back2" type="button" variant="outline" onClick={() => setStep("step2")}>Back</Button>
                      <Button id="save" type="button" onClick={() => void save()}>Save profile</Button>
                    </div>
                  </>
                ) : null}
                {id === "step4" ? (
                  <>
                    <h2 className="m-0 font-display text-[1.6rem] leading-none font-extrabold [font-family:var(--font-display)]">Resume PDF</h2>
                    <Input id="resume" type="file" accept="application/pdf" onChange={(event) => setResumeFile(event.target.files?.[0] ?? null)} />
                    <div className="flex gap-2">
                      <Button id="uploadResume" type="button" onClick={() => void uploadResume()}>Upload resume</Button>
                      <Button id="skipResume" type="button" variant="outline" onClick={() => assignHref("/board")}>Skip for now</Button>
                    </div>
                    <p id="resumeOk" className="m-0 text-sm">{resumeOk}</p>
                  </>
                ) : null}
              </motion.div>
            </div>
          ))}
        </div>
      </main>
    </AppShell>
  );
}
