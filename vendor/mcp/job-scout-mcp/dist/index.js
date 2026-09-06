#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { applyFilters, rankJobs } from "./filter.js";
import { formatJobs } from "./format.js";
import { enabledSources, sourceByName, ALL_SOURCES } from "./sources/index.js";
import { fetchGreenhouse } from "./sources/greenhouse.js";
import { fetchLever } from "./sources/lever.js";
import { fetchAshby } from "./sources/ashby.js";
import { adzunaSalaryHistogram } from "./sources/adzuna.js";
const server = new McpServer({
    name: "job-scout-mcp",
    version: "0.1.0",
});
const SENIORITY = z
    .enum(["any", "mid", "senior", "lead", "manager", "director", "vp", "exec"])
    .describe("Only return roles at or above this seniority level.");
/** Run a query across the requested (or all enabled) sources. */
async function runSearch(query, sourceNames) {
    const sources = sourceNames?.length
        ? sourceNames.map(sourceByName).filter((s) => Boolean(s))
        : enabledSources();
    const results = await Promise.allSettled(sources.map((s) => s.search(query)));
    const jobs = results.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
    const filtered = applyFilters(jobs, query);
    const ranked = rankJobs(filtered);
    return ranked.slice(0, query.limit ?? 25);
}
server.registerTool("search_jobs", {
    title: "Search jobs",
    description: "Search job openings across all enabled sources (Greenhouse/Lever/Ashby " +
        "tracked companies, Hacker News 'Who is hiring', RemoteOK, and optionally " +
        "Adzuna/USAJobs). Supports free-text, location, seniority, remote-only, and " +
        "date filters. Ideal for scouting senior/leadership roles.",
    inputSchema: {
        query: z.string().optional().describe("Free-text terms matched against title/description."),
        location: z.string().optional().describe("Location term, matched loosely."),
        minSeniority: SENIORITY.optional(),
        remoteOnly: z.boolean().optional().describe("Restrict to remote-friendly roles."),
        postedAfter: z
            .string()
            .optional()
            .describe("ISO date (YYYY-MM-DD); only roles posted on/after this date."),
        limit: z.number().int().min(1).max(100).optional().describe("Max results (default 25)."),
        sources: z
            .array(z.string())
            .optional()
            .describe("Restrict to specific source names (see list_sources)."),
    },
}, async (args) => {
    const jobs = await runSearch({
        query: args.query,
        location: args.location,
        minSeniority: args.minSeniority,
        remoteOnly: args.remoteOnly,
        postedAfter: args.postedAfter,
        limit: args.limit,
    }, args.sources);
    const header = `### ${jobs.length} role(s) found`;
    return { content: [{ type: "text", text: formatJobs(jobs, header) }] };
});
server.registerTool("list_company_jobs", {
    title: "List a company's open roles",
    description: "Fetch all public postings from a single company's ATS job board. " +
        "Provider is one of greenhouse, lever, or ashby; slug is the company " +
        "identifier from its careers URL (e.g. boards.greenhouse.io/<slug>).",
    inputSchema: {
        provider: z.enum(["greenhouse", "lever", "ashby"]),
        slug: z.string().describe("Company identifier in the ATS URL."),
        query: z.string().optional().describe("Optional free-text filter."),
        minSeniority: SENIORITY.optional(),
    },
}, async (args) => {
    let jobs;
    try {
        if (args.provider === "greenhouse")
            jobs = await fetchGreenhouse(args.slug);
        else if (args.provider === "lever")
            jobs = await fetchLever(args.slug);
        else
            jobs = await fetchAshby(args.slug);
    }
    catch (err) {
        return {
            isError: true,
            content: [
                {
                    type: "text",
                    text: `Could not load ${args.provider}:${args.slug} — ${err.message}`,
                },
            ],
        };
    }
    const filtered = rankJobs(applyFilters(jobs, { query: args.query, minSeniority: args.minSeniority }));
    const header = `### ${args.slug} — ${filtered.length} open role(s) via ${args.provider}`;
    return { content: [{ type: "text", text: formatJobs(filtered, header) }] };
});
server.registerTool("salary_context", {
    title: "Salary distribution for a role",
    description: "Return the salary distribution (histogram) for a role and optional " +
        "location, powered by Adzuna. Requires ADZUNA_APP_ID/ADZUNA_APP_KEY.",
    inputSchema: {
        role: z.string().describe("Role title, e.g. 'engineering director'."),
        location: z.string().optional().describe("Optional location term."),
    },
}, async (args) => {
    const hist = await adzunaSalaryHistogram(args.role, args.location);
    if (!hist) {
        return {
            isError: true,
            content: [
                {
                    type: "text",
                    text: "Adzuna is not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY (free at developer.adzuna.com).",
                },
            ],
        };
    }
    const rows = Object.entries(hist.buckets)
        .sort((a, b) => Number(a[0]) - Number(b[0]))
        .map(([salary, count]) => `- ${Number(salary).toLocaleString()}: ${count} role(s)`);
    const text = `### Salary distribution for "${args.role}"` +
        `${args.location ? ` in ${args.location}` : ""} (${hist.country.toUpperCase()})\n\n` +
        (rows.length ? rows.join("\n") : "_No salary data returned._");
    return { content: [{ type: "text", text }] };
});
server.registerTool("list_sources", {
    title: "List job sources",
    description: "Show every source, whether it is currently enabled, and why any are " +
        "disabled. Useful for diagnosing configuration.",
    inputSchema: {},
}, async () => {
    const rows = ALL_SOURCES.map((s) => {
        const on = s.isEnabled();
        const status = on ? "✅ enabled" : "⬜ disabled";
        const reason = on ? "" : ` — ${s.disabledReason ?? "not configured"}`;
        return `- **${s.name}**: ${status}${reason}`;
    });
    return {
        content: [{ type: "text", text: `### Sources\n\n${rows.join("\n")}` }],
    };
});
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
    // Log to stderr only — stdout is reserved for the MCP protocol.
    console.error("job-scout-mcp running on stdio");
}
main().catch((err) => {
    console.error("Fatal error starting job-scout-mcp:", err);
    process.exit(1);
});
//# sourceMappingURL=index.js.map