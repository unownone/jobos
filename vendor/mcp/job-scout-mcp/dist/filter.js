/** Ordinal ranking used to compare seniority levels. */
const SENIORITY_RANK = {
    any: 0,
    mid: 1,
    senior: 2,
    lead: 3,
    manager: 4,
    director: 5,
    vp: 6,
    exec: 7,
};
/**
 * Title keywords that signal a seniority level. Order does not matter; we take
 * the highest level whose keywords appear in the title.
 */
const SENIORITY_KEYWORDS = [
    { level: "exec", patterns: [/\bC[TEFOI]O\b/i, /chief\b/i, /\bpresident\b/i] },
    { level: "vp", patterns: [/\bVP\b/i, /vice president/i, /\bhead of\b/i] },
    { level: "director", patterns: [/\bdirector\b/i, /\bdir\b/i] },
    { level: "manager", patterns: [/\bmanager\b/i, /\bmgr\b/i, /\bmanagement\b/i] },
    { level: "lead", patterns: [/\blead\b/i, /\bprincipal\b/i, /\bstaff\b/i] },
    { level: "senior", patterns: [/\bsenior\b/i, /\bsr\.?\b/i] },
    { level: "mid", patterns: [/\bmid\b/i, /\bII\b/, /\bintermediate\b/i] },
];
/** Infer a seniority level from a job title. Returns "any" when unknown. */
export function inferSeniority(title) {
    let best = "any";
    for (const { level, patterns } of SENIORITY_KEYWORDS) {
        if (patterns.some((p) => p.test(title))) {
            if (SENIORITY_RANK[level] > SENIORITY_RANK[best])
                best = level;
        }
    }
    return best;
}
function matchesText(job, query) {
    if (!query)
        return true;
    const haystack = `${job.title} ${job.department ?? ""} ${job.snippet ?? ""}`.toLowerCase();
    // All whitespace-separated terms must appear (AND semantics).
    return query
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
        .every((term) => haystack.includes(term));
}
function matchesLocation(job, location) {
    if (!location)
        return true;
    return job.location.toLowerCase().includes(location.toLowerCase());
}
function matchesDate(job, postedAfter) {
    if (!postedAfter || !job.postedAt)
        return true;
    return new Date(job.postedAt).getTime() >= new Date(postedAfter).getTime();
}
/**
 * Apply the query's cross-cutting filters to an already-fetched list. Sources
 * do coarse server-side filtering where they can; this guarantees consistent
 * behavior across sources that cannot.
 */
export function applyFilters(jobs, query) {
    const min = query.minSeniority ?? "any";
    const minRank = SENIORITY_RANK[min];
    return jobs.filter((job) => {
        if (!matchesText(job, query.query))
            return false;
        if (!matchesLocation(job, query.location))
            return false;
        if (query.remoteOnly && job.remote !== true)
            return false;
        if (!matchesDate(job, query.postedAfter))
            return false;
        if (minRank > 0 && SENIORITY_RANK[inferSeniority(job.title)] < minRank) {
            return false;
        }
        return true;
    });
}
/** Newest first, then by title for stable output. */
export function rankJobs(jobs) {
    return [...jobs].sort((a, b) => {
        const ta = a.postedAt ? new Date(a.postedAt).getTime() : 0;
        const tb = b.postedAt ? new Date(b.postedAt).getTime() : 0;
        if (tb !== ta)
            return tb - ta;
        return a.title.localeCompare(b.title);
    });
}
/** Strip HTML tags and collapse whitespace into a short plain-text snippet. */
export function toSnippet(html, max = 240) {
    if (!html)
        return undefined;
    const text = html
        .replace(/<[^>]+>/g, " ")
        .replace(/&[a-z]+;/gi, " ")
        .replace(/\s+/g, " ")
        .trim();
    if (!text)
        return undefined;
    return text.length > max ? `${text.slice(0, max)}…` : text;
}
//# sourceMappingURL=filter.js.map