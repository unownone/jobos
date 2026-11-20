import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { assignHref, errorText, postJson } from "@/lib/auth-post";

const display = "font-display tracking-[-0.03em] [font-family:var(--font-display)]";

function bootstrapFromHash(): string {
  const hash = window.location.hash.replace(/^#/, "");
  return new URLSearchParams(hash).get("bootstrap") ?? "";
}

export function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(bootstrapFromHash);
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    try {
      const res = await postJson("/api/auth/bootstrap", {
        email: email.trim(),
        password,
        token: token.trim(),
      });
      if (!res.ok) {
        setError(await errorText(res));
        return;
      }
      assignHref("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-background px-4 py-8 text-foreground">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-start gap-3">
            <img
              src="/brand/mascot.png"
              alt="jobOS"
              width={40}
              height={40}
              className="size-10 rounded-md object-cover"
            />
            <div className="flex flex-col gap-1">
              <h1 className={`${display} text-[1.7rem] leading-none font-extrabold`}>Create the jobOS admin</h1>
              <p className="text-sm text-muted-foreground">
                One-time bootstrap. Admin is a human owner, not a job-search track. Token is not stored after signup.
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form id="form" className="flex flex-col gap-4" onSubmit={(event) => void onSubmit(event)}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="token">Bootstrap token</Label>
              <Input
                id="token"
                name="token"
                type="password"
                autoComplete="off"
                required
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
            </div>
            <Button type="submit">Create admin</Button>
            <div id="err" className="min-h-5 text-sm text-destructive" role="alert">
              {error}
            </div>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
