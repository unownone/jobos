import { Source } from "../types.js";
/**
 * Hacker News runs a monthly "Ask HN: Who is hiring?" thread (by user
 * `whoishiring`). Each top-level comment is one company's posting. We use the
 * free Algolia HN API to find the latest thread and read its comments.
 */
export declare const hnHiringSource: Source;
