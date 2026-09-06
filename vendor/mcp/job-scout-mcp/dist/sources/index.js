import { greenhouseSource } from "./greenhouse.js";
import { leverSource } from "./lever.js";
import { ashbySource } from "./ashby.js";
import { remoteOkSource } from "./remoteok.js";
import { hnHiringSource } from "./hnhiring.js";
import { adzunaSource } from "./adzuna.js";
import { usaJobsSource } from "./usajobs.js";
/** All sources known to the server, in default query order. */
export const ALL_SOURCES = [
    greenhouseSource,
    leverSource,
    ashbySource,
    hnHiringSource,
    remoteOkSource,
    adzunaSource,
    usaJobsSource,
];
export function enabledSources() {
    return ALL_SOURCES.filter((s) => s.isEnabled());
}
export function sourceByName(name) {
    return ALL_SOURCES.find((s) => s.name === name);
}
//# sourceMappingURL=index.js.map