import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
/**
 * Hacker News runs a monthly "Ask HN: Who is hiring?" thread (by user
 * `whoishiring`). Each top-level comment is one company's posting. We use the
 * free Algolia HN API to find the latest thread and read its comments.
 */
export const hnHiringSource = {
    name: "hnhiring",
    isEnabled: () => true,
    async search(_query) {
        // 1. Find the most recent "Who is hiring?" story.
        const search = await fetchJson("https://hn.algolia.com/api/v1/search?tags=story,author_whoishiring&query=Who%20is%20hiring&hitsPerPage=3");
        const story = search.hits.find((h) => /who is hiring/i.test(h.title ?? ""));
        if (!story)
            return [];
        // 2. Load its top-level comments (one posting each).
        const item = await fetchJson(`https://hn.algolia.com/api/v1/items/${story.objectID}`);
        const comments = (item.children ?? []).filter((c) => c.text);
        return comments.map((c) => {
            const text = decodeHtml(c.text ?? "");
            return {
                id: `hnhiring:${c.id}`,
                title: firstLine(text),
                company: parseCompany(text),
                location: parseLocation(text),
                url: `https://news.ycombinator.com/item?id=${c.id}`,
                source: "hnhiring",
                postedAt: c.created_at,
                remote: /\bremote\b/i.test(text),
                snippet: toSnippet(text),
            };
        });
    },
};
/** HN comment bodies are HTML; strip to plain text for parsing. */
function decodeHtml(s) {
    return s
        .replace(/<[^>]+>/g, " ")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&")
        .replace(/&quot;/g, '"')
        .replace(/&#x27;|&#39;/g, "'")
        .replace(/&#x2F;/g, "/")
        .replace(/\s+/g, " ")
        .trim();
}
function firstLine(text) {
    const line = text.split(/[.|\n]/)[0].trim();
    return line.length > 120 ? `${line.slice(0, 120)}…` : line || "HN posting";
}
/** Postings usually start "COMPANY | role | ...". Grab the leading segment. */
function parseCompany(text) {
    const seg = text.split("|")[0].trim();
    return seg.length > 0 && seg.length < 60 ? seg : "See posting";
}
function parseLocation(text) {
    const m = text.match(/\b(remote|onsite|hybrid|[A-Z][a-z]+,?\s?[A-Z]{2})\b/);
    return m ? m[0] : "See posting";
}
//# sourceMappingURL=hnhiring.js.map