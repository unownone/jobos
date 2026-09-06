import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
/**
 * RemoteOK publishes a free JSON feed of remote roles. Usage requires
 * attribution back to remoteok.com, which we honor in the tool output.
 */
export const remoteOkSource = {
    name: "remoteok",
    isEnabled: () => true,
    async search(_query) {
        const data = await fetchJson("https://remoteok.com/api");
        return (data ?? [])
            .filter((item) => !item.legal && item.position)
            .map((item) => ({
            id: `remoteok:${item.id ?? item.slug ?? item.position}`,
            title: item.position,
            company: item.company ?? "Unknown",
            location: item.location?.trim() || "Remote",
            url: item.url || item.apply_url || `https://remoteok.com/remote-jobs/${item.slug ?? ""}`,
            source: "remoteok",
            postedAt: item.date,
            remote: true,
            snippet: toSnippet(item.description),
        }));
    },
};
//# sourceMappingURL=remoteok.js.map