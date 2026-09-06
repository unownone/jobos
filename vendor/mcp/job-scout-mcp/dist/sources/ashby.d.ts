import { Job, Source } from "../types.js";
/**
 * Fetch public postings from a company's Ashby job board.
 * `slug` is the company identifier in jobs.ashbyhq.com/<slug>.
 */
export declare function fetchAshby(slug: string): Promise<Job[]>;
export declare const ashbySource: Source;
