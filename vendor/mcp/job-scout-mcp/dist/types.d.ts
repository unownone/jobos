/**
 * A single normalized job posting. Every source maps its raw response into
 * this shape so tools can filter, rank, and render results uniformly.
 */
export interface Job {
    /** Stable-ish identifier, prefixed by source (e.g. "greenhouse:stripe:12345"). */
    id: string;
    title: string;
    company: string;
    location: string;
    /** Canonical apply/listing URL. */
    url: string;
    /** Which source produced this record. */
    source: string;
    /** ISO 8601 posting date if the source provides one. */
    postedAt?: string;
    department?: string;
    /** Remote/hybrid/onsite when the source signals it. */
    remote?: boolean;
    /** Free-text salary string or normalized range summary. */
    salary?: string;
    /** Short description snippet (plain text, trimmed). */
    snippet?: string;
}
/** Normalized query passed to every source. Sources ignore fields they cannot honor. */
export interface JobQuery {
    /** Free-text terms matched against title (and description where available). */
    query?: string;
    /** Location term; matched loosely against the posting location. */
    location?: string;
    /** Only return roles at or above this seniority. */
    minSeniority?: Seniority;
    /** Restrict to remote-friendly roles. */
    remoteOnly?: boolean;
    /** Only roles posted on/after this ISO date. */
    postedAfter?: string;
    /** Max results per source. */
    limit?: number;
}
export type Seniority = "any" | "mid" | "senior" | "lead" | "manager" | "director" | "vp" | "exec";
/** Contract every source module implements. */
export interface Source {
    /** Stable name, e.g. "greenhouse". */
    name: string;
    /** True when required credentials/config are present. */
    isEnabled(): boolean;
    /** Human-readable reason a source is disabled (for diagnostics). */
    disabledReason?: string;
    /** Run a query and return normalized jobs. Should throw on hard errors. */
    search(query: JobQuery): Promise<Job[]>;
}
