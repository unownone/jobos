import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { config } from "../config.js";
import { Job, JobQuery, Source } from "../types.js";

interface AdzunaResult {
  id: string;
  title: string;
  company?: { display_name?: string };
  location?: { display_name?: string };
  redirect_url: string;
  created?: string;
  description?: string;
  salary_min?: number;
  salary_max?: number;
  contract_time?: string;
}

interface AdzunaSearchResponse {
  results: AdzunaResult[];
}

interface AdzunaHistogram {
  histogram: Record<string, number>;
}

function enabled(): boolean {
  return Boolean(config.adzuna.appId && config.adzuna.appKey);
}

function creds(): string {
  return `app_id=${encodeURIComponent(config.adzuna.appId)}&app_key=${encodeURIComponent(
    config.adzuna.appKey,
  )}`;
}

function formatSalary(min?: number, max?: number): string | undefined {
  if (!min && !max) return undefined;
  if (min && max) return `${Math.round(min)}–${Math.round(max)}`;
  return `${Math.round((min || max) as number)}`;
}

export const adzunaSource: Source = {
  name: "adzuna",
  isEnabled: enabled,
  disabledReason: "Set ADZUNA_APP_ID and ADZUNA_APP_KEY (free at developer.adzuna.com)",
  async search(query: JobQuery): Promise<Job[]> {
    const country = config.adzuna.country;
    const params = new URLSearchParams();
    if (query.query) params.set("what", query.query);
    if (query.location) params.set("where", query.location);
    params.set("results_per_page", String(Math.min(query.limit ?? 20, 50)));
    if (query.remoteOnly) params.set("what_and", "remote");

    const url = `https://api.adzuna.com/v1/api/jobs/${country}/search/1?${creds()}&${params}`;
    const data = await fetchJson<AdzunaSearchResponse>(url);
    return (data.results ?? []).map((r) => ({
      id: `adzuna:${r.id}`,
      title: r.title,
      company: r.company?.display_name ?? "Unknown",
      location: r.location?.display_name ?? "Unspecified",
      url: r.redirect_url,
      source: "adzuna",
      postedAt: r.created,
      remote: r.description ? /\bremote\b/i.test(r.description) : undefined,
      salary: formatSalary(r.salary_min, r.salary_max),
      snippet: toSnippet(r.description),
    }));
  },
};

/**
 * Salary distribution for a role/region, powered by Adzuna's histogram
 * endpoint. Returns null when Adzuna is not configured.
 */
export async function adzunaSalaryHistogram(
  role: string,
  location?: string,
): Promise<{ country: string; buckets: Record<string, number> } | null> {
  if (!enabled()) return null;
  const country = config.adzuna.country;
  const params = new URLSearchParams({ what: role });
  if (location) params.set("where", location);
  const url = `https://api.adzuna.com/v1/api/jobs/${country}/histogram?${creds()}&${params}`;
  const data = await fetchJson<AdzunaHistogram>(url);
  return { country, buckets: data.histogram ?? {} };
}
