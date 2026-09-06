import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { config } from "../config.js";
function enabled() {
    return Boolean(config.usajobs.apiKey && config.usajobs.email);
}
export const usaJobsSource = {
    name: "usajobs",
    isEnabled: enabled,
    disabledReason: "Set USAJOBS_API_KEY and USAJOBS_EMAIL (free at developer.usajobs.gov)",
    async search(query) {
        const params = new URLSearchParams();
        if (query.query)
            params.set("Keyword", query.query);
        if (query.location)
            params.set("LocationName", query.location);
        params.set("ResultsPerPage", String(Math.min(query.limit ?? 25, 50)));
        const url = `https://data.usajobs.gov/api/search?${params}`;
        const data = await fetchJson(url, {
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
                salary: pay?.MinimumRange && pay?.MaximumRange
                    ? `${pay.MinimumRange}–${pay.MaximumRange}`
                    : undefined,
                snippet: toSnippet(d.UserArea?.Details?.JobSummary),
            };
        });
    },
};
//# sourceMappingURL=usajobs.js.map