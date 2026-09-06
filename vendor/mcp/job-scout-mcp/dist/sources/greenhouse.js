import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { config } from "../config.js";
/**
 * Fetch every public posting from a company's Greenhouse job board.
 * `slug` is the company identifier in boards.greenhouse.io/<slug>.
 */
export async function fetchGreenhouse(slug) {
    const url = `https://boards-api.greenhouse.io/v1/boards/${encodeURIComponent(slug)}/jobs?content=true`;
    const data = await fetchJson(url);
    return (data.jobs ?? []).map((j) => ({
        id: `greenhouse:${slug}:${j.id}`,
        title: j.title,
        company: slug,
        location: j.location?.name ?? "Unspecified",
        url: j.absolute_url,
        source: "greenhouse",
        postedAt: j.updated_at,
        department: j.departments?.map((d) => d.name).filter(Boolean).join(", ") || undefined,
        snippet: toSnippet(j.content ? decodeHtml(j.content) : undefined),
    }));
}
/** Greenhouse serves job content HTML-encoded; decode the common entities. */
function decodeHtml(s) {
    return s
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'");
}
export const greenhouseSource = {
    name: "greenhouse",
    isEnabled: () => config.trackedCompanies.some((c) => c.provider === "greenhouse"),
    disabledReason: "No greenhouse companies in TRACKED_COMPANIES (add e.g. greenhouse:stripe)",
    async search(_query) {
        const slugs = config.trackedCompanies
            .filter((c) => c.provider === "greenhouse")
            .map((c) => c.slug);
        const results = await Promise.allSettled(slugs.map(fetchGreenhouse));
        return results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
    },
};
//# sourceMappingURL=greenhouse.js.map