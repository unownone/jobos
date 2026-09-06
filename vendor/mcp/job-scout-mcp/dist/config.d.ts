/**
 * Central configuration read once from environment variables.
 * Everything here is optional — the server runs fully on keyless sources.
 */
export interface TrackedCompany {
    provider: "greenhouse" | "lever" | "ashby";
    slug: string;
}
export declare const config: {
    adzuna: {
        appId: string;
        appKey: string;
        country: string;
    };
    usajobs: {
        apiKey: string;
        email: string;
    };
    trackedCompanies: TrackedCompany[];
    cacheTtlSeconds: number;
    contact: string;
};
export declare const USER_AGENT: string;
