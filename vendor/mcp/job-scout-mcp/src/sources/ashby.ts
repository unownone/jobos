import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { config } from "../config.js";
import { Job, JobQuery, Source } from "../types.js";

interface AshbyJob {
  id: string;
  title: string;
  location?: string;
  department?: string;
  team?: string;
  isRemote?: boolean;
  publishedAt?: string;
  jobUrl?: string;
  applyUrl?: string;
  descriptionPlain?: string;
  compensation?: { compensationTierSummary?: string };
}

interface AshbyResponse {
  jobs: AshbyJob[];
}

/**
 * Fetch public postings from a company's Ashby job board.
 * `slug` is the company identifier in jobs.ashbyhq.com/<slug>.
 */
export async function fetchAshby(slug: string): Promise<Job[]> {
  const url = `https://api.ashbyhq.com/posting-api/job-board/${encodeURIComponent(
    slug,
  )}?includeCompensation=true`;
  const data = await fetchJson<AshbyResponse>(url);
  return (data.jobs ?? []).map((j) => ({
    id: `ashby:${slug}:${j.id}`,
    title: j.title,
    company: slug,
    location: j.location ?? "Unspecified",
    url: j.jobUrl || j.applyUrl || "",
    source: "ashby",
    postedAt: j.publishedAt,
    department: j.department || j.team,
    remote: j.isRemote,
    salary: j.compensation?.compensationTierSummary,
    snippet: toSnippet(j.descriptionPlain),
  }));
}

export const ashbySource: Source = {
  name: "ashby",
  isEnabled: () => config.trackedCompanies.some((c) => c.provider === "ashby"),
  disabledReason: "No ashby companies in TRACKED_COMPANIES (add e.g. ashby:notion)",
  async search(_query: JobQuery): Promise<Job[]> {
    const slugs = config.trackedCompanies
      .filter((c) => c.provider === "ashby")
      .map((c) => c.slug);
    const results = await Promise.allSettled(slugs.map(fetchAshby));
    return results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
  },
};
