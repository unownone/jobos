import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { config } from "../config.js";
import { Job, JobQuery, Source } from "../types.js";

interface UsaJobsResponse {
  SearchResult?: {
    SearchResultItems?: Array<{
      MatchedObjectDescriptor?: {
        PositionID?: string;
        PositionTitle?: string;
        OrganizationName?: string;
        PositionURI?: string;
        PublicationStartDate?: string;
        PositionLocationDisplay?: string;
        UserArea?: { Details?: { JobSummary?: string } };
        PositionRemuneration?: Array<{
          MinimumRange?: string;
          MaximumRange?: string;
        }>;
      };
    }>;
  };
}

function enabled(): boolean {
  return Boolean(config.usajobs.apiKey && config.usajobs.email);
}

export const usaJobsSource: Source = {
  name: "usajobs",
  isEnabled: enabled,
  disabledReason:
    "Set USAJOBS_API_KEY and USAJOBS_EMAIL (free at developer.usajobs.gov)",
  async search(query: JobQuery): Promise<Job[]> {
    const params = new URLSearchParams();
    if (query.query) params.set("Keyword", query.query);
    if (query.location) params.set("LocationName", query.location);
    params.set("ResultsPerPage", String(Math.min(query.limit ?? 25, 50)));

    const url = `https://data.usajobs.gov/api/search?${params}`;
    const data = await fetchJson<UsaJobsResponse>(url, {
      headers: {
        Host: "data.usajobs.gov",
        "User-Agent": config.usajobs.email,
        "Authorization-Key": config.usajobs.apiKey,
      },
    });

    const items = data.SearchResult?.SearchResultItems ?? [];
    return items.map((item) => {
      const d = item.MatchedObjectDescriptor ?? {};
      const pay = d.PositionRemuneration?.[0];
      return {
        id: `usajobs:${d.PositionID ?? d.PositionURI ?? ""}`,
        title: d.PositionTitle ?? "Untitled",
        company: d.OrganizationName ?? "US Federal Government",
        location: d.PositionLocationDisplay ?? "United States",
        url: d.PositionURI ?? "",
        source: "usajobs",
        postedAt: d.PublicationStartDate,
        salary:
          pay?.MinimumRange && pay?.MaximumRange
            ? `${pay.MinimumRange}–${pay.MaximumRange}`
            : undefined,
        snippet: toSnippet(d.UserArea?.Details?.JobSummary),
      } satisfies Job;
    });
  },
};
