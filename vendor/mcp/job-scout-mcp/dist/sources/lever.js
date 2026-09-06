import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { config } from "../config.js";
/**
 * Fetch public postings from a company's Lever board.
 * `slug` is the company identifier in jobs.lever.co/<slug>.
 */
export async function fetchLever(slug) {
    const url = `https://api.lever.co/v0/postings/${encodeURIComponent(slug)}?mode=json`;
    const data = await fetchJson(url);
    return (data ?? []).map((p) => ({
        id: `lever:${slug}:${p.id}`,
        title: p.text,
        company: slug,
        location: p.categories?.location ?? "Unspecified",
        url: p.hostedUrl || p.applyUrl || "",
        source: "lever",
        postedAt: p.createdAt ? new Date(p.createdAt).toISOString() : undefined,
        department: p.categories?.team,
        remote: p.workplaceType ? /remote/i.test(p.workplaceType) : undefined,
        snippet: toSnippet(p.descriptionPlain),
    }));
}
export const leverSource = {
    name: "lever",
    isEnabled: () => config.trackedCompanies.some((c) => c.provider === "lever"),
    disabledReason: "No lever companies in TRACKED_COMPANIES (add e.g. lever:netflix)",
    async search(_query) {
        const slugs = config.trackedCompanies
            .filter((c) => c.provider === "lever")
            .map((c) => c.slug);
        const results = await Promise.allSettled(slugs.map(fetchLever));
        return results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
    },
};
//# sourceMappingURL=lever.js.map