import { config, USER_AGENT } from "./config.js";
const cache = new Map();
/**
 * Fetch JSON with a small in-memory TTL cache and a descriptive User-Agent.
 * The cache keeps us polite toward public endpoints that have no formal
 * rate limits. Non-2xx responses throw with the status for easy diagnostics.
 */
export async function fetchJson(url, init = {}, ttlSeconds = config.cacheTtlSeconds) {
    const key = cacheKey(url, init);
    const now = Date.now();
    const hit = cache.get(key);
    if (hit && hit.expires > now) {
        return hit.body;
    }
    const headers = new Headers(init.headers);
    if (!headers.has("User-Agent"))
        headers.set("User-Agent", USER_AGENT);
    if (!headers.has("Accept"))
        headers.set("Accept", "application/json");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    let res;
    try {
        res = await fetch(url, { ...init, headers, signal: controller.signal });
    }
    finally {
        clearTimeout(timeout);
    }
    if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`Request to ${url} failed: ${res.status} ${res.statusText}${text ? ` — ${text.slice(0, 200)}` : ""}`);
    }
    const body = (await res.json());
    if (ttlSeconds > 0) {
        cache.set(key, { expires: now + ttlSeconds * 1000, body });
    }
    return body;
}
function cacheKey(url, init) {
    const method = (init.method || "GET").toUpperCase();
    const body = typeof init.body === "string" ? init.body : "";
    return `${method} ${url} ${body}`;
}
//# sourceMappingURL=http.js.map