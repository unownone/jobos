/**
 * Fetch JSON with a small in-memory TTL cache and a descriptive User-Agent.
 * The cache keeps us polite toward public endpoints that have no formal
 * rate limits. Non-2xx responses throw with the status for easy diagnostics.
 */
export declare function fetchJson<T = unknown>(url: string, init?: RequestInit, ttlSeconds?: number): Promise<T>;
