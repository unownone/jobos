import { Source } from "../types.js";
/** All sources known to the server, in default query order. */
export declare const ALL_SOURCES: Source[];
export declare function enabledSources(): Source[];
export declare function sourceByName(name: string): Source | undefined;
