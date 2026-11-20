import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { assignHref, errorText, postJson } from "@/lib/auth-post";
import { nextPath } from "@/lib/next-path";

const display = "font-display tracking-[-0.03em] [font-family:var(--font-display)]";

type AuthKind = "login" | "signup";

type CandidateStatus = {
  candidate_onboarded?: boolean;
  onboarded?: boolean;
};

function savedUsername(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem("jobos_username") ?? "";
  } catch {
    return "";
  }
}

function authPath(kind: AuthKind): string {
  switch (kind) {
    case "login":
      return "/api/auth/login";
    case "signup":
      return "/api/auth/signup";
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

function destination(status: CandidateStatus): string {
  const explicit = status.candidate_onboarded;
  const onboarded = typeof explicit === "boolean" ? explicit : status.onboarded;
  if (onboarded === true) {
    return nextPath(new URLSearchParams(window.location.search).get("next"));
  }
  return "/onboarding";
}

export function LoginPage() {
  const [username, setUsername] = useState(savedUsername);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function send(kind: AuthKind) {
    setError("");
    const name = username.trim();
    try {
      const res = await postJson(authPath(kind), { username: name, password });
      if (!res.ok) {
        setError(await errorText(res));
        return;
      }
      try {
        window.localStorage.setItem("jobos_username", name);
      } catch {
        // Storage can be blocked. The session still stands.
      }
      const status = await api<CandidateStatus>("/api/candidate/status");
      assignHref(destination(status));
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send("login");
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-background px-4 py-8 text-foreground">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-start gap-3">
            <img
              src="/brand/mascot.png"
              alt="jobOS Stitch"
              width={40}
              height={40}
              className="size-10 rounded-md object-cover"
            />
            <div className="flex flex-col gap-1">
              <h1 className={`${display} text-[1.7rem] leading-none font-extrabold`}>jobOS Harness</h1>
              <p className="text-sm text-muted-foreground">
                Log in or create an account. Each account is isolated — jobs, resumes, and queue traffic stay in
                your tenant.
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form id="form" className="flex flex-col gap-4" onSubmit={onSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" className="min-w-[8rem] flex-1">
                Log in
              </Button>
              <Button
                type="button"
                id="signupBtn"
                variant="secondary"
                className="min-w-[8rem] flex-1"
                onClick={() => void send("signup")}
              >
                Create account
              </Button>
            </div>
            <div id="err" className="min-h-5 text-sm text-destructive" role="alert">
              {error}
            </div>
          </form>
          <p className="mt-4 text-sm text-muted-foreground">
            Session lasts 12 hours of idle. Username + password only — no dashboard token.
          </p>
          <p className="mt-2 text-sm">
            <a href="/" className="text-accent-foreground underline-offset-4 hover:underline">
              Back to landing
            </a>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
