# Coherent Hub UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated static Hub pages with one React UI where every control is a shadcn component, every screen scrolls inside one shell, and page changes use Framer Motion, while FastAPI routes, cookies, and the pinned HTML/DOM contract keep working.

**Architecture:** A Vite React app in `board/web` is the only operator and public UI. It hydrates prerendered HTML files that FastAPI already serves from `board/app/static/`. The shell owns the viewport (`h-dvh overflow-hidden`); each pane owns its scroll (`min-h-0 flex-1 overflow-y-auto`). shadcn is themed to the existing terminal-ops tokens. The Python API stays the source of truth; change it only when a screen cannot express an existing behavior.

**Tech Stack:** React 19, TypeScript, Vite 6, Tailwind CSS 4, shadcn/ui (Radix), Framer Motion 12, Vitest, Testing Library. FastAPI continues to serve HTML and `/api/*`.

## Global Constraints

- Visual world is industrial terminal-ops. Do not invent a second palette. Hex values are exactly: chassis `#0b1220`, chassis-2 `#101827`, panel `#172033`, bezel `#243044`, ink `#f3eee3`, ink-dim `#cbb892`, amber `#e0992d`, amber-hot `#f3bc5a`, amber-deep `#b57516`, good `#3f9d7a`, warn `#c9893a`, bad `#c45c4a`, console `#070b12`, stop `#8a3228`.
- Radius is `2px`. Pill radius `999px` is only the phone Jobs/Live switch. Sheet radius `12px` is only the mobile ticket. Touch target is `44px` (`2.75rem`).
- Type: Big Shoulders Display for display headings, Red Hat Text for UI, Red Hat Mono for code. Files already exist at `/static/fonts/*.woff2`. Do not download new fonts.
- Brand images stay `/brand/mascot.png`, `/brand/logo.png`, `/brand/favicon.png`. The rail brand mark renders the mascot image, not initials.
- Preserve these visible strings: `All statuses`, `jobOS Harness`, `helps find jobs`, `Hunt funnel`, `Skill registry`, `Memory pods`, `jobOS data`, `Candidate onboarding`, `Directory`, `Join`, `Oldest open job`, `Create account`, `Find jobs`, `Get started`.
- Preserve these DOM ids because Playwright and `board/tests/test_board.py` read them: `username`, `password`, `signupBtn`, `err`, `whoLabel`, `logoutBtn`, `connLabel`, `pager`, `moreFilters`, `q`, `statusBtn`, `list`, `side`, `f_company`, `f_title`, `f_status`, `f_rejection_by`, `f_company_remarks`, `f_user_remarks`, `sideErr`, `full_name`, `email`, `titles`, `locations_t`, `headline`, `stack`, `revLine`, `ok`, `step2`, `step4`, `resume`, `formPanel`, `who`, `track`, `created`, `url`, `prompt`, `rows`, `add-item`, `compose-status`, `skills`, `msg`, `table`, `stats`, `form`, `key`, `name`.
- `data-solidify` stays on the memory Solidify button. `id="add-item"` stays on the memory Add button.
- Unauthorized `/board` redirects to `/login?next=/board`, never `/login?next=/`. A `next` of `/` or empty becomes `/board` (`nextPath` below).
- Session is the `hub_csrf` cookie. Mutating fetches send header `X-CSRF` and `credentials: "same-origin"`.
- `prefers-reduced-motion: reduce` uses opacity only. Do not animate `y` or any other transform, including with duration 0. `pageVariants(true)` is the helper.
- Do not invent a candidate, employer, or metric. Do not put secrets in the repo.
- Python deps stay in `board/` via `uv`. Node deps stay in `board/web/`.
- Imports go at the top of each module. Switches over unions end with a `never` check.

## Corrections already in the code

These were raised against the plan commit and are implemented. Later tasks must not undo them.

- Login and bootstrap POST do not go through `api()`. A 401 must stay on the form and fill `#err`. `api()` still redirects other 401s.
- The login card's Create account button posts `{ username, password }` to `/api/auth/signup`. `/admin/signup` posts `{ email, password, token }` to `/api/auth/bootstrap`.
- Candidate status uses `onboarded` from `GET /api/candidate/status`. `candidate_onboarded` is only a fallback when that field is a boolean.
- `nextPath` resolves the value against an app origin and returns `/board` when the origin differs, or when the decoded path contains `\` or starts with `//`.
- `api()` accepts `raw` plus `contentType` for the resume PDF. Object `body` stays JSON.
- `AppShell` takes an optional `path`. Prerender passes the route. The browser falls back to `window.location.pathname`.

## Why the current UI fails

`.hub-stage` in `board/app/static/hub.css` is `height: 100dvh; max-height: 100dvh; overflow: hidden` while the header, two filter rows, queue rail, and pager are siblings of the board. Any of those rows growing (wrapped filters, long status text, the mobile dock) clips the list with no document scroll. The same rail, dock, CSRF helper, and logout handler are copied into `home.html`, `index.html`, `admin.html`, `data.html`, `users.html`, `skills.html`, `memory.html`, and `onboarding.html`. `login.html`, `memory.html`, `skills.html`, and `index.html` each implement `api()` differently.

Superdesign could not draft this: `superdesign.dev` is outside the pod egress allowlist, and `superdesign login` failed twice with `Client network socket disconnected before secure TLS connection was established`. Direction is the committed `DESIGN.md` and `board/app/static/theme.css`.

## File map

- Create `board/web/` — Vite app.
- Create `board/web/src/index.css` — Tailwind plus the token mapping below. Do not restate the palette in component files.
- Create `board/web/src/lib/api.ts` — one fetch wrapper.
- Create `board/web/src/lib/next-path.ts` — login redirect rule.
- Create `board/web/src/lib/motion.ts` — shared variants.
- Create `board/web/src/components/shell/` — `AppShell`, `Rail`, `Dock`, `TopBar`.
- Create `board/web/src/components/ui/` — shadcn primitives only, generated by the shadcn CLI, then restyled only through `index.css` tokens.
- Create `board/web/src/pages/` — one file per route.
- Create `board/web/scripts/prerender.ts` — writes the HTML files FastAPI already serves.
- Modify `board/tests/test_ui_shell.py` only in Task 10, when vanilla function-source assertions no longer match the prerendered HTML.
- Leave `board/app/main.py` route paths unchanged. Prerender overwrites the HTML files those routes already return.

## Scroll contract

```tsx
// board/web/src/components/shell/AppShell.tsx
// scroll="page": the stage body scrolls (home, admin, onboarding, public pages).
// scroll="panes": the stage body does not scroll; the page puts overflow-y-auto on each pane
// (board list, presence rail, ticket). Header and pager stay visible.
```

The document element and `body` are `overflow: hidden; height: 100dvh`. A test fails if a page root uses `h-screen` together with `overflow-hidden` on an ancestor that also contains a growing toolbar without `min-h-0`.

---

### Task 1: Scaffold the component app and lock the tokens

**Files:**
- Create: `board/web/package.json`
- Create: `board/web/vite.config.ts`
- Create: `board/web/tsconfig.json`
- Create: `board/web/tsconfig.app.json`
- Create: `board/web/src/index.css`
- Create: `board/web/src/main.tsx`
- Create: `board/web/src/vite-env.d.ts`
- Create: `board/web/src/lib/tokens.test.ts`
- Test: `board/web/src/lib/tokens.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces: CSS variables `--background`, `--foreground`, `--card`, `--primary`, `--primary-foreground`, `--muted`, `--muted-foreground`, `--destructive`, `--border`, `--ring`, `--radius` with the hex values in Global Constraints. Vite dev server proxies `/api`, `/static`, `/brand`, `/health` to `http://127.0.0.1:8787`.

- [ ] **Step 1: Write the failing token test**

```ts
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../index.css"),
  "utf8",
);

describe("terminal-ops tokens", () => {
  it("maps shadcn variables onto the chassis palette", () => {
    expect(css).toContain("--background: #0b1220");
    expect(css).toContain("--foreground: #f3eee3");
    expect(css).toContain("--card: #172033");
    expect(css).toContain("--primary: #e0992d");
    expect(css).toContain("--primary-foreground: #0b1220");
    expect(css).toContain("--muted-foreground: #cbb892");
    expect(css).toContain("--destructive: #c45c4a");
    expect(css).toContain("--ring: #e0992d");
    expect(css).toContain("--radius: 2px");
  });
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd board/web && npm test -- src/lib/tokens.test.ts`

Expected: FAIL because `board/web` does not exist yet. Create the package first if npm cannot run, then re-run and expect FAIL with "no such file".

- [ ] **Step 3: Scaffold**

`board/web/package.json`:

```json
{
  "name": "jobos-hub-ui",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build && tsx scripts/prerender.ts",
    "test": "vitest run",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "framer-motion": "^12.0.0",
    "class-variance-authority": "^0.7.1",
    "clsx": "^2.1.1",
    "tailwind-merge": "^3.0.0",
    "lucide-react": "^0.475.0",
    "@radix-ui/react-slot": "^1.1.2"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.2.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^26.0.0",
    "tailwindcss": "^4.0.0",
    "tsx": "^4.19.0",
    "typescript": "^5.7.0",
    "vite": "^6.1.0",
    "vitest": "^3.0.0"
  }
}
```

Install with `cd board/web && npm install`. Then add shadcn primitives used by later tasks:

```bash
cd board/web
npx shadcn@latest init -y -b radix
npx shadcn@latest add button input textarea label select dropdown-menu scroll-area sheet tabs badge card separator dialog sonner
```

If the CLI prompts, choose TypeScript, Vite, `@/` alias, and the CSS file `src/index.css`. After generation, replace color values in `src/index.css` so the test strings exist verbatim. Keep shadcn's `@import "tailwindcss"` and `@theme inline` block, but set:

```css
:root {
  --background: #0b1220;
  --foreground: #f3eee3;
  --card: #172033;
  --card-foreground: #f3eee3;
  --popover: #172033;
  --popover-foreground: #f3eee3;
  --primary: #e0992d;
  --primary-foreground: #0b1220;
  --secondary: #101827;
  --secondary-foreground: #f3eee3;
  --muted: #101827;
  --muted-foreground: #cbb892;
  --accent: #243044;
  --accent-foreground: #f3bc5a;
  --destructive: #c45c4a;
  --border: rgba(224, 153, 45, 0.32);
  --input: rgba(224, 153, 45, 0.5);
  --ring: #e0992d;
  --radius: 2px;
  --font-display: "Big Shoulders Display", "Arial Narrow", sans-serif;
  --font-sans: "Red Hat Text", "Segoe UI", sans-serif;
  --font-mono: "Red Hat Mono", ui-monospace, monospace;
}
```

Add font faces pointing at `/static/fonts/big-shoulders-display-700.woff2`, `big-shoulders-display-800.woff2`, `red-hat-text-400.woff2`, `red-hat-text-500.woff2`, `red-hat-text-600.woff2`, `red-hat-mono-400.woff2`, `red-hat-mono-500.woff2`.

`board/web/vite.config.ts`:

```ts
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/static": "http://127.0.0.1:8787",
      "/brand": "http://127.0.0.1:8787",
      "/health": "http://127.0.0.1:8787",
    },
  },
  test: { environment: "jsdom", setupFiles: "./src/test-setup.ts" },
});
```

`src/test-setup.ts` imports `@testing-library/jest-dom/vitest`.

`src/main.tsx` renders a placeholder `<div id="main">jobOS Harness</div>` into `#root`. Do not delete the existing static HTML in this task.

- [ ] **Step 4: Run the token test**

Run: `cd board/web && npm test -- src/lib/tokens.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add board/web
git commit -m "feat: scaffold shadcn hub ui on terminal-ops tokens"
```

---

### Task 2: One shell, one scroll owner, one motion language

**Files:**
- Create: `board/web/src/lib/motion.ts`
- Create: `board/web/src/components/shell/nav.ts`
- Create: `board/web/src/components/shell/AppShell.tsx`
- Create: `board/web/src/components/shell/Rail.tsx`
- Create: `board/web/src/components/shell/Dock.tsx`
- Create: `board/web/src/components/shell/TopBar.tsx`
- Create: `board/web/src/components/shell/AppShell.test.tsx`
- Test: `board/web/src/components/shell/AppShell.test.tsx`

**Interfaces:**
- Consumes: shadcn `Button`, `ScrollArea` from Task 1
- Produces:
  - `NAV` constant: `{ href, label, icon }[]` for Home `/home`, Board `/board`, Directory `/admin/users`, Invites `/admin`, Data `/admin/data`, Skills `/admin/skills`, Memory `/admin/memory`, Candidate `/onboarding`
  - `export function AppShell({ title, subtitle, scroll, who, children }: { title: string; subtitle?: string; scroll: "page" | "panes"; who?: string; children: React.ReactNode })`
  - `export const pageMotion` and `export function usePageTransition()` from `motion.ts`. `usePageTransition()` returns `{ duration: 0 }` when `useReducedMotion()` is true, otherwise `{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }`.

- [ ] **Step 1: Write the failing shell test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

describe("AppShell", () => {
  it("keeps the document from scrolling and gives the page a scrollport", () => {
    render(
      <AppShell title="jobOS Harness" subtitle="helps find jobs" scroll="page">
        <p>Hunt funnel</p>
      </AppShell>,
    );
    const frame = screen.getByTestId("hub-frame");
    const port = screen.getByTestId("hub-scroll");
    expect(frame.className).toContain("overflow-hidden");
    expect(frame.className).toContain("h-dvh");
    expect(port.className).toContain("overflow-y-auto");
    expect(port.className).toContain("min-h-0");
    expect(screen.getByRole("navigation", { name: "Hub" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Directory" })).toHaveAttribute("href", "/admin/users");
    expect(screen.getByText("helps find jobs")).toBeInTheDocument();
  });

  it("does not scroll the stage when panes own the scroll", () => {
    render(
      <AppShell title="jobOS Harness" scroll="panes">
        <div>list</div>
      </AppShell>,
    );
    expect(screen.getByTestId("hub-scroll").className).not.toContain("overflow-y-auto");
  });
});
```

- [ ] **Step 2: Run it**

Run: `cd board/web && npm test -- src/components/shell/AppShell.test.tsx`

Expected: FAIL, `AppShell` is not defined.

- [ ] **Step 3: Implement**

`motion.ts`:

```ts
import { useReducedMotion } from "framer-motion";

export const pageMotion = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -6 },
};

export function usePageTransition() {
  const reduce = useReducedMotion();
  if (reduce) return { duration: 0 };
  return { duration: 0.18, ease: [0.2, 0.8, 0.2, 1] as const };
}
```

`nav.ts` exports `NAV` with the eight links above. Labels are exactly `Home`, `Board`, `Directory`, `Invites`, `Data`, `Skills`, `Memory`, `Candidate`.

`AppShell` structure:

- Outer `div` `data-testid="hub-frame"` with classes `grid h-dvh overflow-hidden bg-background text-foreground grid-cols-[5.5rem_minmax(0,1fr)] max-[959px]:grid-cols-1 max-[959px]:pb-[calc(3.5rem+env(safe-area-inset-bottom))]`.
- `Rail` is a `<nav aria-label="Hub">` hidden below 960px (`max-[959px]:hidden`), sticky, full height, mascot linking to `/home`.
- Stage is `flex min-h-0 min-w-0 flex-col`.
- `TopBar` shows `title` in Big Shoulders (`font-display text-[1.35rem]`) and optional subtitle.
- Scroll region `data-testid="hub-scroll"` `id` is not `main` (pages supply `#main`). Classes: `flex min-h-0 flex-1 flex-col`. Add `overflow-y-auto overflow-x-hidden` only when `scroll === "page"`.
- Children render inside `motion.div` using `pageMotion` and `usePageTransition()`.
- `Dock` is `fixed inset-x-0 bottom-0 z-30 hidden max-[959px]:grid grid-cols-4` with Home, Board, Directory, and a More button. More opens a shadcn `Sheet` containing Invites, Data, Skills, Memory, Candidate, and Log out. The dock does not cover the scrollport because the frame already pads the bottom.

Active link: `aria-current="page"` when `window.location.pathname` equals `href`, or when href is `/admin` and the path is `/admin` or `/admin/invites`.

- [ ] **Step 4: Run the test**

Run: `cd board/web && npm test -- src/components/shell/AppShell.test.tsx`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add board/web/src/components/shell board/web/src/lib/motion.ts
git commit -m "feat: add hub shell with a single scroll owner"
```

---

### Task 3: Shared API client and login next-path

**Files:**
- Create: `board/web/src/lib/api.ts`
- Create: `board/web/src/lib/next-path.ts`
- Create: `board/web/src/lib/api.test.ts`
- Create: `board/web/src/lib/next-path.test.ts`
- Test: those two test files

**Interfaces:**
- Consumes: nothing from the shell
- Produces:
  - `export function nextPath(requested: string | null): string`
  - `export function csrfToken(): string`
  - `export async function api<T>(path: string, opts?: { method?: string; body?: unknown }): Promise<T>`
  - On HTTP 401, `api` sets `window.location.href` to `/login?next=` + `nextPath(window.location.pathname)` and throws `Error("unauthorized")`.

`nextPath` rules, matching `board/app/static/login.html`:

- `null`, `""`, `"/"`, and any value that does not start with `/` or starts with `//` returns `"/board"`.
- Any other path is returned unchanged.

`csrfToken` reads cookie `hub_csrf`. `api` always sends `credentials: "same-origin"`, `Content-Type: application/json` when `body` is present, and `X-CSRF` when the cookie is present. JSON body is `JSON.stringify(opts.body)`. Non-OK responses throw `Error` whose message is `detail` when it is a string, otherwise `JSON.stringify(detail)`.

- [ ] **Step 1: Write the failing tests**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextPath } from "./next-path";

describe("nextPath", () => {
  it("sends the public root to the board", () => {
    expect(nextPath("/")).toBe("/board");
    expect(nextPath(null)).toBe("/board");
    expect(nextPath("")).toBe("/board");
    expect(nextPath("//evil.example")).toBe("/board");
  });

  it("keeps an in-app path", () => {
    expect(nextPath("/admin/memory")).toBe("/admin/memory");
  });
});
```

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, csrfToken } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "hub_csrf=; Max-Age=0";
});

describe("api", () => {
  it("sends the csrf cookie on mutating calls", async () => {
    document.cookie = "hub_csrf=abc%3D123";
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(csrfToken()).toBe("abc=123");
    await api("/api/jobs/j", { method: "PATCH", body: { title: "Staff" } });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["X-CSRF"]).toBe("abc=123");
    expect(init.body).toBe(JSON.stringify({ title: "Staff" }));
  });

  it("redirects 401 to the board when next would be root", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    window.history.pushState({}, "", "/");
    await expect(api("/api/whoami")).rejects.toThrow("unauthorized");
    expect(window.location.pathname + window.location.search).toBe("/login?next=/board");
  });
});
```

- [ ] **Step 2: Run both tests and confirm FAIL**

Run: `cd board/web && npm test -- src/lib/api.test.ts src/lib/next-path.test.ts`

Expected: FAIL, modules missing.

- [ ] **Step 3: Implement `next-path.ts` and `api.ts` to the rules above**

- [ ] **Step 4: Re-run the tests**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add board/web/src/lib/api.ts board/web/src/lib/api.test.ts board/web/src/lib/next-path.ts board/web/src/lib/next-path.test.ts
git commit -m "feat: share hub fetch and login next-path"
```

---

### Task 4: Public landing and get-started

**Files:**
- Create: `board/web/src/pages/LandingPage.tsx`
- Create: `board/web/src/pages/StartPage.tsx`
- Create: `board/web/src/pages/LandingPage.test.tsx`
- Test: `board/web/src/pages/LandingPage.test.tsx`

**Interfaces:**
- Consumes: `AppShell` is not used. Public pages use a mast (`<header>`) and `<main id="main">`, still inside a `h-dvh overflow-hidden` frame whose `<main>` is `overflow-y-auto`.
- Produces: `LandingPage` and `StartPage` components.

Landing copy (keep the current argument, do not invent employers):

- `h1` contains `Find jobs`.
- A link named `Log in` points at `/login`.
- A link named `Get started` points at `/start`.
- Sections keep ids `capabilities`, `loop`, `start`.
- The loop rail id is `loop-rail`.

Start page:

- `h1` contains `Get started`.
- Body contains the text `candidate_required`.
- Element id `coming-soon` stays.

Read `board/app/static/landing.html` and `start.html` and carry the existing sentences across. Do not add testimonials or fake metrics.

- [ ] **Step 1: Failing test** asserting `Find jobs`, link `Log in`, and that the rendered frame has `overflow-hidden` while `main` has `overflow-y-auto`.

- [ ] **Step 2: Run and confirm FAIL**

- [ ] **Step 3: Implement both pages with shadcn `Button` as the primary and secondary links (`asChild`).** Motion: the hero fades in through `pageMotion`.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `feat: rebuild public landing on the shared shell`

---

### Task 5: Login and bootstrap signup

**Files:**
- Create: `board/web/src/pages/LoginPage.tsx`
- Create: `board/web/src/pages/SignupPage.tsx`
- Create: `board/web/src/pages/LoginPage.test.tsx`
- Test: `board/web/src/pages/LoginPage.test.tsx`

**Interfaces:**
- Consumes: `api`, `nextPath`
- Produces: pages that render without a session

Login form ids: `form`, `username`, `password`, `signupBtn`, `err`. `signupBtn` text is `Create account`. Submit `POST /api/auth/login` with `{ username, password }`. Then `GET /api/candidate/status`. If `candidate_onboarded` is false, go to `/onboarding`. Otherwise go to `nextPath(new URLSearchParams(location.search).get("next"))`.

Signup page ids: `form`, `email`, `password`, `token`, `err`. Submit `POST /api/auth/bootstrap` with `{ email, password, token }`. The token field is the bootstrap secret from the URL hash `bootstrap=`.

Both pages are centered cards (`max-w-md`), not the operator rail. The card is a shadcn `Card`. Inputs are shadcn `Input`. Errors render in `#err`.

- [ ] **Step 1: Test** that login renders `#username` and the Create account button, and that submitting with a mocked 200 then a status of `{ candidate_onboarded: false }` assigns `location.href` to `/onboarding`.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `feat: rebuild login and signup with shadcn fields`

---

### Task 6: Home dashboard

**Files:**
- Create: `board/web/src/pages/HomePage.tsx`
- Create: `board/web/src/pages/HomePage.test.tsx`
- Test: `board/web/src/pages/HomePage.test.tsx`

**Interfaces:**
- Consumes: `AppShell` `scroll="page"`, `api`
- Produces: `HomePage`

On mount, `GET /api/whoami` then `GET /api/dashboard`. 401 is handled by `api`.

Dashboard JSON:

```ts
type Dashboard = {
  funnel: { found: number; applied: number; outreached: number };
  agents: { total: number; working: number; live: number };
  today: { found: number; applied: number; day_start: string };
  oldest_in_pipeline: null | {
    id: string;
    company: string;
    title: string;
    status: string;
    location: string;
    pay: string;
    posted_at: string;
    created_at: string;
    days_in_pipeline: number;
    posted_known: boolean;
  };
};
```

Required visible text and ids, even before data returns:

- Title `jobOS Harness`
- Subtitle contains `helps find jobs`
- `h2` text `Hunt funnel`
- `h2` text `Oldest open job`
- ids `whoLabel`, `logoutBtn`, `connLabel`, `kpiFoundToday`, `kpiAppliedToday`, `kpiOldestDays`, `kpiOldestSub`, `funnelLegend`, `agentWorking`, `oldestBody`, `main`

Fill `kpiFoundToday` from `today.found`, `kpiAppliedToday` from `today.applied`, `kpiOldestDays` from `oldest_in_pipeline.days_in_pipeline` or `—`. `oldestBody` shows company, title, and status. `funnelLegend` lists `Found`, `Applied`, `Outreached` with the three counts. `agentWorking` shows `agents.working`.

Charts: do not import Chart.js. Render the funnel as three shadcn `Card`s or a CSS bar (width percentage of the max count) inside `#funnelLegend`'s section. The heading stays `Hunt funnel`.

`logoutBtn` calls `POST /api/auth/logout` then sets location to `/login`.

`whoLabel` text is `{display_name || actor || user_id} · {kind || role}`.

- [ ] **Step 1: Test** render with mocked `api` returning a fixture `{ funnel: { found: 3, applied: 1, outreached: 0 }, agents: { total: 2, working: 1, live: 1 }, today: { found: 2, applied: 1, day_start: "2026-11-20T00:00:00Z" }, oldest_in_pipeline: { id: "j", company: "TicketCo", title: "Staff", status: "discovered", location: "", pay: "", posted_at: "", created_at: "", days_in_pipeline: 4, posted_known: false } }` and assert `Hunt funnel`, `Oldest open job`, `TicketCo`, and `4`.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement inside `AppShell`**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `feat: rebuild home funnel on the shared shell`

---

### Task 7: Board, ticket, and presence

**Files:**
- Create: `board/web/src/pages/BoardPage.tsx`
- Create: `board/web/src/pages/BoardPage.test.tsx`
- Test: `board/web/src/pages/BoardPage.test.tsx`

**Interfaces:**
- Consumes: `AppShell` with `scroll="panes"`, `api`
- Produces: `BoardPage`

This is the page `test_board.py` and `e2e/test_admin_shell.py` grep. The first render, before `whoami` resolves, must already contain:

- text `jobOS Harness`
- text `helps find jobs`
- button text `All statuses` with id `statusBtn`
- `id="pager"`
- `id="moreFilters"`
- `id="list"`
- `id="q"`
- `id="logoutBtn"`
- `id="whoLabel"`
- `id="connLabel"` whose initial text is `signing in`
- no text `Select a job`
- no `id="connectForm"`

Layout inside the stage: toolbar and `#moreFilters` stay put when they fit. When their combined height leaves the list shorter than `8rem`, the stage itself scrolls (`overflow-y-auto`) so the toolbar, filters, list, and `#pager` all stay reachable. Otherwise the stage does not scroll, and a row `min-h-0 flex-1` contains `#presenceRail` (`overflow-y-auto`), `#list` (`overflow-y-auto`), and `#side`. `#pager` sits under that row and does not scroll away with the list. Below 960px, presence is hidden unless the Jobs/Live switch (`data-board-pane`) is `presence`, and `#side` is a shadcn `Sheet` (`side="bottom"`). Pass `path` into `AppShell` (the route string). Do not read `window.location` during prerender.

Boot sequence from `board/app/static/index.html`:

1. `GET /api/whoami` then `GET /api/meta`.
2. `whoLabel` becomes `{display_name || actor || user_id} · {kind || role}`. `connLabel` becomes `signed in`.
3. `GET /api/jobs` with query keys only when set: `q`, `status`, `stopped`, `lane`, `apply_kind`, `score_min`, `remote`, `has_pay`, `location`, `source`, plus always `limit` and `offset`.
4. Stats text: `{count} shown · {matched} match · {total} total · {role}`.
5. Page label: `Page {n} of {pages}`.
6. Every 10s, `POST /api/presence/heartbeat` with `{ status_hint: "working", task_id, task_kind: "job", job_id }` when a row is open, otherwise `{ status_hint: "logged_in" }`. Then `GET /api/presence`.
7. Admins (`can_hygiene` or `kind === "owner"` or `role === "admin"`) also `GET /api/queue?limit=20` into `#queueStats`.

Ticket `#side` fields, ids exact: `f_company`, `f_title`, `f_source`, `f_status`, `f_score`, `f_location`, `f_apply_url`, `f_posted_at`, `f_pay`, `f_description`, `f_expectations`, `f_notes`, `f_rejection_by`, `f_company_remarks`, `f_user_remarks`, `f_owners`, `f_apply_packet`, `f_outreach_packet`, `f_proof`, `saveBtn`, `pauseBtn`, `stopBtn`, `resumeBtn`, `delBtn`, `sideErr`, `closeSide`. Label text `Rejected by` stays next to `f_rejection_by`.

Save sends `PATCH /api/jobs/{id}` with the body built in `index.html` `saveJob`, then deletes keys not listed in `whoami.patch_fields`. Success sets `#sideErr` to `Saved.` (the current page uses `Saved.`).

Pause `POST /api/jobs/{id}/pause` body `{ reason }` from `window.prompt("Pause reason (required). Status stays; lanes cannot patch until Resume.")`. Stop uses `window.prompt("Stop reason (required). Sets closed_withdrawn and freezes the row.")` and `POST .../stop`. Resume `POST .../resume`. Delete confirms then `DELETE /api/jobs/{id}`.

Row click on `#list tr` opens the ticket. Empty list copy is `Loading jobs…` then, after a successful empty fetch, `No jobs on this page.` Do not use `Select a job`.

- [ ] **Step 1: Test** the initial render contains `All statuses`, `#pager`, `#moreFilters`, and does not contain `Select a job`. Second test: mocked jobs `[{ id: "1", company: "TicketCo", title: "Staff", status: "discovered", stopped: false }]` render inside `#list`, click reveals `#f_company` value `TicketCo`.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement.** Use shadcn `Input`, `Textarea`, `Select`, `Button`, `DropdownMenu`, `ScrollArea`, `Sheet`, `Badge`. The status pill is a `Badge` with a dashed border. Table header sticks inside `#list`'s scrollport (`sticky top-0`), not the document.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `feat: rebuild the job board without clipping the list`

---

### Task 8: Operator admin pages

**Files:**
- Create: `board/web/src/pages/InvitesPage.tsx`
- Create: `board/web/src/pages/UsersPage.tsx`
- Create: `board/web/src/pages/DataPage.tsx`
- Create: `board/web/src/pages/SkillsPage.tsx`
- Create: `board/web/src/pages/MemoryPage.tsx`
- Create: `board/web/src/pages/admin.test.tsx`
- Test: `board/web/src/pages/admin.test.tsx`

**Interfaces:**
- Consumes: `AppShell` `scroll="page"`, `api`
- Produces: the five pages. Each page's growing content sits in the shell scrollport. Tables use `overflow-x-auto` on a wrapper with `min-w-0`, never `width: max-content` on the stage.

Read the current pages and preserve behavior:

- Invites (`admin.html`): title contains `jobOS Harness`. ids `who`, `logout`, `track`, `created`, `url`, `prompt`, `rows`, `soon`. `POST /api/invites`. Revoke `POST /api/invites/{id}/revoke`. `#rows` shows the track name. `#created` contains `/join/`.
- Directory (`users.html`): nav label `Directory`. `GET /api/users` into `#rows`. Heartbeat once on load via `POST /api/presence/heartbeat`.
- Data (`data.html`): `h1` text `jobOS data`. ids `tabs`, `filters`, `stats`, `err`, `table`, `who`. Tabs for jobs, people, candidate, skills, mcps, memory. Jobs filter ids `q`, `status`, `stopped`, `go` when the jobs tab is active. Table body is `#table`.
- Skills (`skills.html`): `h1` contains `Skill registry`. ids `tag`, `scope`, `reload`, `seed`, `msg`, `skills`, `recordings`, `who`, `logout`. Reload calls `GET /api/registry/skills`. Seed calls `POST /api/registry/seed` and sets `#msg` to a string containing `Seeded`.
- Memory (`memory.html`): `h1` contains `Memory pods`. ids `write-pod`, `write-kind`, `write-company`, `write-title`, `write-body`, `add-item`, `save-item`, `cancel-edit`, `compose-status`, `pod`, `q`, `kind`, `load`, `policy`, `err`, `rows`, `share-pod`, `share-kind`, `share-copy`, `share-go`. Add calls `POST /api/memory/items`. A successful add sets `#compose-status` to a string containing `Stored`. Solidify buttons use attribute `data-solidify` equal to the item id and call `POST /api/memory/items/{id}/solidify`.

- [ ] **Step 1: One test file** with five cases, each rendering the page and asserting the heading and the primary id (`add-item`, `Skill registry`, `jobOS data`, `track`, `rows`).

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement all five, using shadcn `Tabs`, `Select`, `Input`, `Textarea`, `Button`, `Table` markup with `ScrollArea` only if the shadcn table is not added — a plain `<table>` inside `overflow-x-auto` is required either way.**

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `feat: rebuild admin pages on the shared shell`

---

### Task 9: Onboarding and join

**Files:**
- Create: `board/web/src/pages/OnboardingPage.tsx`
- Create: `board/web/src/pages/JoinPage.tsx`
- Create: `board/web/src/pages/OnboardingPage.test.tsx`
- Test: `board/web/src/pages/OnboardingPage.test.tsx`

**Interfaces:**
- Consumes: `AppShell` for onboarding (`scroll="page"`), `api`, `nextPath` is not used here
- Produces: both pages

Onboarding heading text is `Candidate onboarding`. Steps are four regions. ids that exist in the document even when hidden: `step1`, `step2`, `step3`, `step4`, `s1`, `s2`, `s3`, `s4`, `formPanel`, `full_name`, `preferred_name`, `email`, `phone`, `location`, `timezone`, `work_authorization`, `linkedin_url`, `github_url`, `to2`, `titles`, `locations_t`, `seniority`, `domains`, `remote`, `must_haves`, `deal_breakers`, `back1`, `to3`, `headline`, `years`, `stack`, `highlights`, `do_not_claim`, `writing_voice`, `back2`, `save`, `resume`, `uploadResume`, `skipResume`, `resumeOk`, `err`, `ok`, `revLine`, `who`.

`GET /api/candidate` prefills the fields. `to2` with empty name or email sets `#err` to text containing `Full name and email` and does not reveal step 2. `to3` with empty titles sets `#err` to text containing `title`. Save `PUT /api/candidate` with the same JSON shape `onboarding.html` sends today (read that file's save handler and copy the keys). Success sets `#ok` to text containing `Profile saved` and reveals `#step4`. Resume upload calls `api("/api/candidate/resume", { method: "PUT", raw: fileBytes, contentType: "application/pdf" })`. Do not `JSON.stringify` the PDF. Skip sets location to `/board`, never `/` and never `/admin`. Pass `path` into `AppShell`.

Join page is not inside the operator rail. Heading contains `Join`. ids `title`, `blurb`, `payload`, `form`, `name`, `model`, `harness`, `bed`, `provider`, `capabilities`, `extra`, `err`, `key`. Load `GET /api/join/{id}?s=`. Register `POST /api/auth/join`. The one-time key renders in `#key` and includes the text `API key`. If the API says onboarding is incomplete, `#blurb` contains `Candidate onboarding`.

- [ ] **Step 1: Test** empty identity blocks step 2, and a mocked save shows `Profile saved` and `#step4`.

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement.** Use shadcn inputs. Step changes animate with `pageMotion` and honor reduced motion.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit** `feat: rebuild onboarding and join on shadcn fields`

---

### Task 10: Prerender into the files FastAPI already serves

**Files:**
- Create: `board/web/scripts/prerender.ts`
- Modify: `board/app/static/landing.html`
- Modify: `board/app/static/start.html`
- Modify: `board/app/static/login.html`
- Modify: `board/app/static/signup.html`
- Modify: `board/app/static/home.html`
- Modify: `board/app/static/index.html`
- Modify: `board/app/static/admin.html`
- Modify: `board/app/static/data.html`
- Modify: `board/app/static/users.html`
- Modify: `board/app/static/skills.html`
- Modify: `board/app/static/memory.html`
- Modify: `board/app/static/onboarding.html`
- Modify: `board/app/static/join.html`
- Modify: `board/tests/test_ui_shell.py`
- Modify: `board/app/main.py` only if the built CSS/JS need a new mount. Prefer writing assets to `board/app/static/app/` which the existing `/static` mount already serves.
- Test: `board/tests/test_ui_shell.py`, `board/tests/test_board.py::test_ui_is_served`

**Interfaces:**
- Consumes: every page component
- Produces: static HTML containing the pinned strings, plus a module script whose `src` is the file Vite emitted (read `manifest.json`; do not invent a hashed name). `main.tsx` hydrates `#root` by choosing the page from `<body data-page="...">`. The Vite entry is `board/web/index.html`, which already exists. Pass each route into `AppShell` as `path` so prerender does not touch `window`.

Prerender uses `renderToString` for the logged-out shell of each page so the strings exist without running the browser. `data-page` values: `landing`, `start`, `login`, `signup`, `home`, `board`, `invites`, `data`, `users`, `skills`, `memory`, `onboarding`, `join`.

Each HTML document includes:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<link rel="stylesheet" href="/static/theme.css" />
<link rel="stylesheet" href="/static/app/APP_CSS" />
```

`APP_CSS` is the stylesheet path Vite wrote, taken from the build manifest. Do not hardcode `app.css` unless `build.rollupOptions.output.assetFileNames` actually emits that name. The test must assert the href that the built HTML contains.

`test_ui_shell.py` today asserts vanilla source (`function fillForm`, `function nextPath`, `hub.css` on every page). Replace those assertions with:

- every page file contains `viewport-fit=cover`, `/static/theme.css`, and the same `/static/app/` stylesheet href the prerender wrote
- authenticated pages `index.html`, `home.html`, `admin.html`, `data.html`, `users.html`, `skills.html`, `memory.html`, `onboarding.html` contain `hub-frame` or `data-testid="hub-frame"` and the link `/admin/memory`
- `index.html` contains `id="f_rejection_by"`, `id="f_company_remarks"`, `id="f_user_remarks"`, `Rejected by`, and `/login?next=/board`, and does not contain `/login?next=/`
- `onboarding.html` contains `id="full_name"` and the string `/board` as the post-save destination, and does not contain `location.href = "/"` or `location.href = "/admin"`
- `login.html` contains `id="username"` and `Create account`

Do not keep the `function fillForm` assertion. The behavior is covered by `OnboardingPage.test.tsx`.

Vite `build.outDir` is `board/app/static/app` with `emptyOutDir: true`. Asset base is `/static/app/`.

- [ ] **Step 1: Update `test_ui_shell.py` first** so the new assertions fail against today's HTML.

- [ ] **Step 2: Run** `cd board && uv run pytest tests/test_ui_shell.py -q` and confirm FAIL.

- [ ] **Step 3: Implement prerender and point `main.tsx` at the page map.** Run `cd board/web && npm run build`.

- [ ] **Step 4: Run** `cd board && uv run pytest tests/test_ui_shell.py tests/test_board.py::test_ui_is_served -q`

Expected: PASS. `test_ui_is_served` still sees `All statuses`, `jobOS Harness`, `helps find jobs`, `id="pager"`, `id="moreFilters"`, `Hunt funnel`, `Oldest open job` in the HTTP body.

- [ ] **Step 5: Commit** `feat: serve the shadcn hub from the existing html routes`

---

### Task 11: Prove scroll and the live flows

**Files:**
- Create: `board/web/src/pages/scroll.contract.test.tsx`
- Test: that file, plus the existing pytest modules that do not need a live browser

**Interfaces:**
- Consumes: `BoardPage`, `HomePage`, `MemoryPage`, `AppShell`
- Produces: a regression test that fails if the board toolbar and the list share a clipping `overflow-hidden` ancestor without a `min-h-0` scrollport between them.

- [ ] **Step 1: Write the test**

Render `BoardPage` with fetch mocked to 401 so it stays on the shell. Assert:

- `[data-testid="hub-frame"]` has `overflow-hidden` and `h-dvh`
- `#list` is inside an element whose class contains `overflow-y-auto` OR `#list` itself does
- `#pager` is not inside that scrollport (the pager stays put)
- no ancestor of `#list` other than the frame has both `overflow-hidden` and a fixed `h-dvh` without an intervening `min-h-0`

- [ ] **Step 2: FAIL if the board page regressed, else PASS**

- [ ] **Step 3: Fix the layout if the test fails. Do not weaken the test.**

- [ ] **Step 4: Run** `cd board/web && npm test` and `cd board && uv run pytest tests/test_ui_shell.py tests/test_board.py tests/test_public_site.py -q`

Expected: web tests PASS. Python tests that only read static HTML and the served board page PASS. If a Python test fails because it required a vanilla function name, update that assertion to the pinned id or string from Global Constraints and re-run. Do not delete coverage of a user-visible behavior.

- [ ] **Step 5: Commit** `test: lock the hub scroll contract`

---

## Self-review

- Spec coverage: shadcn primitives (Task 1), shell and motion (Task 2), one API client (Task 3), public pages (Task 4), auth (Task 5), home (Task 6), board overflow (Task 7), admin (Task 8), onboarding and join (Task 9), served HTML contract (Task 10), scroll regression (Task 11).
- Backend changes are allowed in the task that discovers an API gap. The planned tasks do not require one: every screen calls an existing route.
- Placeholder scan: page tasks name the ids, endpoints, and assertions. Implementers read the current HTML for sentence-level copy and the save payload already quoted for the board.
- Type consistency: `api`, `nextPath`, `AppShell` scroll mode `"page" | "panes"`, and `Dashboard` are defined before the tasks that use them.

## Live evaluation

Hub is up at `http://127.0.0.1:8787` (no Docker; local Postgres). `/opt/cursor/artifacts/audit/FLOWS.md` records 37 flows, 0 failures: health, public pages, signup, candidate gate `409 candidate_required`, onboarding `PUT /api/candidate`, then home, board, admin, data, skills, memory, users, dashboard, jobs, meta, registry (29 skills), memory pods, presence, job create, and pause.

Rendered at 1280×720 after login. `.hub-stage` is `overflow: hidden`. Wheel scroll does not move it (`scrollTop` stays 0).

| Path | Stage scroll height vs 720px client | Content sticks out of the stage | What that means |
| --- | --- | --- | --- |
| `/home` | 720 | no | `.hub-home` is `overflow: auto` |
| `/board` | 720 | no | list pane scrolls |
| `/onboarding` | 862 | yes, bottom at 822 | Next button is clipped |
| `/admin` | 1146 | yes, bottom at 1106 | Railway and Coolify links sit below the fold and cannot be reached |
| `/admin/skills` | 1853 | yes, bottom at 1813 | 29 skill rows, 8 visible, wheel does nothing |
| `/admin/memory` | 1043 | yes, bottom at 1003 | compose and table are clipped |
| `/admin/data` | 720 | no | short empty state only |
| `/admin/users` | 720 | no | short table only |

Tasks 6 through 9 must put page content in `AppShell` `scroll="page"` so this measurement flips: after a wheel, `scrollTop` of the scrollport increases and a control that starts below 720px becomes visible. Task 7 keeps `scroll="panes"` and must keep `#pager` outside the list scrollport. Tables on admin pages need `overflow-x-auto` and `min-w-0` so a 9-column directory does not widen the stage. Close, switch, and menu controls use the 44px touch size (`2.75rem`), not `2.2rem`.

No API change is required for these screens. The routes they call already returned 200.
