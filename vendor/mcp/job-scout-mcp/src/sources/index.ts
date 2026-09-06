import { Source } from "../types.js";
import { greenhouseSource } from "./greenhouse.js";
import { leverSource } from "./lever.js";
import { ashbySource } from "./ashby.js";
import { remoteOkSource } from "./remoteok.js";
import { hnHiringSource } from "./hnhiring.js";
import { adzunaSource } from "./adzuna.js";
import { usaJobsSource } from "./usajobs.js";

/** All sources known to the server, in default query order. */
export const ALL_SOURCES: Source[] = [
  greenhouseSource,
  leverSource,
  ashbySource,
  hnHiringSource,
  remoteOkSource,
  adzunaSource,
  usaJobsSource,
];

export function enabledSources(): Source[] {
  return ALL_SOURCES.filter((s) => s.isEnabled());
}

export function sourceByName(name: string): Source | undefined {
  return ALL_SOURCES.find((s) => s.name === name);
}
