import { fetchJson } from "../http.js";
import { toSnippet } from "../filter.js";
import { Job, JobQuery, Source } from "../types.js";

interface RemoteOkItem {
  id?: string;
  slug?: string;
  position?: string;
  company?: string;
  location?: string;
  url?: string;
  apply_url?: string;
  date?: string;
  description?: string;
  tags?: string[];
  // The first element of the feed is a legal/attribution notice, not a job.
  legal?: string;
}

/**
 * RemoteOK publishes a free JSON feed of remote roles. Usage requires
 * attribution back to remoteok.com, which we honor in the tool output.
 */
export const remoteOkSource: Source = {
  name: "remoteok",
  isEnabled: () => true,
  async search(_query: JobQuery): Promise<Job[]> {
    const data = await fetchJson<RemoteOkItem[]>("https://remoteok.com/api");
    return (data ?? [])
      .filter((item) => !item.legal && item.position)
      .map((item) => ({
        id: `remoteok:${item.id ?? item.slug ?? item.position}`,
        title: item.position as string,
        company: item.company ?? "Unknown",
        location: item.location?.trim() || "Remote",
        url: item.url || item.apply_url || `https://remoteok.com/remote-jobs/${item.slug ?? ""}`,
        source: "remoteok",
        postedAt: item.date,
        remote: true,
        snippet: toSnippet(item.description),
      }));
  },
};
