import { Source } from "../types.js";
export declare const adzunaSource: Source;
/**
 * Salary distribution for a role/region, powered by Adzuna's histogram
 * endpoint. Returns null when Adzuna is not configured.
 */
export declare function adzunaSalaryHistogram(role: string, location?: string): Promise<{
    country: string;
    buckets: Record<string, number>;
} | null>;
