import { useEffect, useState, type FormEvent } from "react";
import { motion, useReducedMotion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { pageVariants, usePageTransition } from "@/lib/motion";

type JoinBody = {
  track?: string;
  mode?: string;
  join_blocked?: boolean;
  candidate?: { onboarded?: boolean };
  detail?: { message?: string } | string;
};

type Registered = {
  kind?: string;
  track?: string;
  api_key?: string;
  detail?: { message?: string } | string;
};

function detailText(detail: JoinBody["detail"], fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  return fallback;
}

export function JoinPage() {
  const reduce = useReducedMotion() === true;
  const variants = pageVariants(reduce);
  const transition = usePageTransition();
  const [title, setTitle] = useState("Join");
  const [blurb, setBlurb] = useState("");
  const [payload, setPayload] = useState("");
  const [err, setErr] = useState("");
  const [keyText, setKeyText] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [harness, setHarness] = useState("");
  const [bed, setBed] = useState("");
  const [provider, setProvider] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [extra, setExtra] = useState("");

  useEffect(() => {
    const parts = window.location.pathname.split("/").filter(Boolean);
    const inviteId = parts[1] || "";
    const secret = new URLSearchParams(window.location.search).get("s") || "";
    let cancelled = false;
    async function load() {
      if (!inviteId || !secret) {
        setErr("This join link is missing the invite id or secret.");
        return;
      }
      const res = await fetch(`/api/join/${encodeURIComponent(inviteId)}?s=${encodeURIComponent(secret)}`);
      const body = (await res.json().catch(() => ({}))) as JoinBody;
      if (cancelled) return;
      if (!res.ok) {
        setErr(detailText(body.detail, res.statusText));
        return;
      }
      setTitle(body.track ? `Joining ${body.track}` : "Join");
      setPayload(JSON.stringify(body, null, 2));
      if (body.join_blocked || !body.candidate?.onboarded) {
        setBlurb("Candidate onboarding is not complete. The human admin must finish /onboarding with a truthful profile before any agent can join. Do not invent a candidate.");
        setOpen(false);
        return;
      }
      setBlurb(`You are joining the ${body.track} track (${body.mode}). First redemption is the owner unless the track already has one. Copy the API key after register — it is shown once.`);
      setOpen(true);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErr("");
    const parts = window.location.pathname.split("/").filter(Boolean);
    const inviteId = parts[1] || "";
    const secret = new URLSearchParams(window.location.search).get("s") || "";
    let extraBody: Record<string, unknown> = {};
    if (extra.trim()) {
      try {
        extraBody = JSON.parse(extra) as Record<string, unknown>;
      } catch {
        setErr("extra JSON is invalid");
        return;
      }
    }
    const caps = capabilities.split(",").map((part) => part.trim()).filter(Boolean);
    const metadata = {
      ...extraBody,
      model: model || undefined,
      harness: harness || undefined,
      bed: bed || undefined,
      provider: provider || undefined,
      capabilities: caps.length ? caps : undefined,
    };
    const res = await fetch("/api/auth/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invite_id: inviteId, s: secret, display_name: name, metadata }),
    });
    const body = (await res.json().catch(() => ({}))) as Registered;
    if (!res.ok) {
      setErr(detailText(body.detail, res.statusText));
      return;
    }
    setOpen(false);
    setKeyText(`Registered as ${body.kind} on ${body.track}. API key (copy now): ${body.api_key}`);
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <motion.main
        id="main"
        className="hub-enter min-h-0 flex-1 overflow-y-auto"
        initial={variants.initial}
        animate={variants.animate}
        transition={transition}
      >
        <div className="mx-auto flex w-full max-w-lg flex-col gap-4 px-4 py-10">
          <h1 id="title" className="m-0 font-display text-[2.4rem] leading-none font-extrabold [font-family:var(--font-display)]">
            {title}
          </h1>
          <p id="blurb" className="m-0 text-muted-foreground">{blurb}</p>
          <pre id="payload" className="min-w-0 max-w-full overflow-x-auto whitespace-pre-wrap break-all border border-border bg-secondary p-3 text-sm">{payload}</pre>
          <form id="form" hidden={!open} className="flex flex-col gap-3" onSubmit={(event) => void onSubmit(event)}>
            <Field>Display name<Input id="name" value={name} onChange={(event) => setName(event.target.value)} /></Field>
            <Field>Model<Input id="model" value={model} onChange={(event) => setModel(event.target.value)} /></Field>
            <Field>Harness<Input id="harness" value={harness} onChange={(event) => setHarness(event.target.value)} /></Field>
            <Field>Bed<Input id="bed" value={bed} onChange={(event) => setBed(event.target.value)} /></Field>
            <Field>Provider<Input id="provider" value={provider} onChange={(event) => setProvider(event.target.value)} /></Field>
            <Field>Capabilities<Input id="capabilities" value={capabilities} onChange={(event) => setCapabilities(event.target.value)} /></Field>
            <Field>extra JSON<Textarea id="extra" value={extra} onChange={(event) => setExtra(event.target.value)} /></Field>
            <Button type="submit">Register</Button>
          </form>
          <p id="err" className="m-0 text-sm text-destructive">{err}</p>
          <p id="key" className="m-0 break-all text-sm">{keyText}</p>
        </div>
      </motion.main>
    </div>
  );
}
