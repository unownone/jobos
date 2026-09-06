/** Render a list of jobs as compact markdown for display in an MCP client. */
export function formatJobs(jobs, header) {
    if (jobs.length === 0) {
        return `${header}\n\n_No matching roles found._`;
    }
    const lines = jobs.map((j, i) => {
        const bits = [
            `**${i + 1}. [${j.title}](${j.url})**`,
            `${j.company} · ${j.location} · \`${j.source}\``,
        ];
        if (j.salary)
            bits.push(`💰 ${j.salary}`);
        if (j.postedAt)
            bits.push(`🗓 ${j.postedAt.slice(0, 10)}`);
        if (j.snippet)
            bits.push(`> ${j.snippet}`);
        return bits.join("\n");
    });
    const usedRemoteOk = jobs.some((j) => j.source === "remoteok");
    const attribution = usedRemoteOk
        ? "\n\n_Remote roles courtesy of [RemoteOK](https://remoteok.com)._"
        : "";
    return `${header}\n\n${lines.join("\n\n")}${attribution}`;
}
//# sourceMappingURL=format.js.map