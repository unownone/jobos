import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

import type { PageName } from "../src/pages/registry";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const staticDir = path.resolve(webRoot, "../app/static");

const TITLES: Record<PageName, string> = {
  landing: "jobOS",
  start: "jobOS — Get started",
  login: "jobOS Harness login",
  signup: "jobOS Harness — First admin",
  home: "jobOS Harness",
  board: "jobOS Harness",
  invites: "jobOS Harness — Invites",
  data: "jobOS data",
  users: "jobOS Harness — Directory",
  skills: "jobOS Harness — Skill registry",
  memory: "jobOS Harness — Memory pods",
  onboarding: "jobOS Harness — Candidate onboarding",
  join: "jobOS — Join",
};

const FILES: Record<PageName, string> = {
  landing: "landing.html",
  start: "start.html",
  login: "login.html",
  signup: "signup.html",
  home: "home.html",
  board: "index.html",
  invites: "admin.html",
  data: "data.html",
  users: "users.html",
  skills: "skills.html",
  memory: "memory.html",
  onboarding: "onboarding.html",
  join: "join.html",
};

type ManifestEntry = { file: string; css?: string[]; isEntry?: boolean };

function assetHrefs(): { css: string; js: string } {
  const manifestPath = path.join(staticDir, "app/.vite/manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, ManifestEntry>;
  const entry = Object.values(manifest).find((item) => item.isEntry);
  const css = entry?.css?.[0];
  if (!entry || !css) {
    throw new Error(`Vite manifest at ${manifestPath} has no entry stylesheet`);
  }
  return { css: `/static/app/${css}`, js: `/static/app/${entry.file}` };
}

function documentFor(name: PageName, body: string, css: string, js: string): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <title>${TITLES[name]}</title>
    <link rel="icon" href="/brand/favicon.png" />
    <link rel="stylesheet" href="/static/theme.css" />
    <link rel="stylesheet" href="${css}" />
  </head>
  <body data-page="${name}">
    <div id="root">${body}</div>
    <script type="module" src="${js}"></script>
  </body>
</html>
`;
}

const vite = await createServer({
  root: webRoot,
  server: { middlewareMode: true },
  appType: "custom",
});

try {
  const { css, js } = assetHrefs();
  const server = (await vite.ssrLoadModule("/src/entry-server.tsx")) as {
    renderPage: (name: PageName) => string;
  };
  for (const name of Object.keys(FILES) as PageName[]) {
    const html = documentFor(name, server.renderPage(name), css, js);
    writeFileSync(path.join(staticDir, FILES[name]), html);
  }
} finally {
  await vite.close();
}
