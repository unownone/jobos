/**
 * Central configuration read once from environment variables.
 * Everything here is optional — the server runs fully on keyless sources.
 */

export interface TrackedCompany {
  provider: "greenhouse" | "lever" | "ashby";
  slug: string;
}

function parseTracked(raw: string | undefined): TrackedCompany[] {
  if (!raw) return [];
  const out: TrackedCompany[] = [];
  for (const part of raw.split(",")) {
    const [provider, slug] = part.trim().split(":");
    if (!provider || !slug) continue;
    if (provider === "greenhouse" || provider === "lever" || provider === "ashby") {
      out.push({ provider, slug });
    }
  }
  return out;
}

export const config = {
  adzuna: {
    appId: process.env.ADZUNA_APP_ID?.trim() || "",
    appKey: process.env.ADZUNA_APP_KEY?.trim() || "",
    country: process.env.ADZUNA_COUNTRY?.trim() || "gb",
  },
  usajobs: {
    apiKey: process.env.USAJOBS_API_KEY?.trim() || "",
    email: process.env.USAJOBS_EMAIL?.trim() || "",
  },
  trackedCompanies: parseTracked(process.env.TRACKED_COMPANIES),
  cacheTtlSeconds: Number(process.env.CACHE_TTL_SECONDS) || 900,
  contact:
    process.env.CONTACT?.trim() ||
    "job-scout-mcp (https://github.com/pabnatanawan87/job-scout-mcp)",
};

export const USER_AGENT = `job-scout-mcp/0.1 ${config.contact}`;
