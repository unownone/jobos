import { Job, JobQuery, Seniority } from "./types.js";
/** Infer a seniority level from a job title. Returns "any" when unknown. */
export declare function inferSeniority(title: string): Seniority;
/**
 * Apply the query's cross-cutting filters to an already-fetched list. Sources
 * do coarse server-side filtering where they can; this guarantees consistent
 * behavior across sources that cannot.
 */
export declare function applyFilters(jobs: Job[], query: JobQuery): Job[];
/** Newest first, then by title for stable output. */
export declare function rankJobs(jobs: Job[]): Job[];
/** Strip HTML tags and collapse whitespace into a short plain-text snippet. */
export declare function toSnippet(html: string | undefined, max?: number): string | undefined;
