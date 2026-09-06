import { Job, Source } from "../types.js";
/**
 * Fetch every public posting from a company's Greenhouse job board.
 * `slug` is the company identifier in boards.greenhouse.io/<slug>.
 */
export declare function fetchGreenhouse(slug: string): Promise<Job[]>;
export declare const greenhouseSource: Source;
