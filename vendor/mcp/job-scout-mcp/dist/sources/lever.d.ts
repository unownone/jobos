import { Job, Source } from "../types.js";
/**
 * Fetch public postings from a company's Lever board.
 * `slug` is the company identifier in jobs.lever.co/<slug>.
 */
export declare function fetchLever(slug: string): Promise<Job[]>;
export declare const leverSource: Source;
