export const STEP1 = ["full_name", "preferred_name", "email", "phone", "location", "timezone", "work_authorization", "linkedin_url", "github_url"];
export const STEP2 = ["titles", "locations", "seniority", "domains", "remote", "must_haves", "deal_breakers"];
export const STEP3 = ["headline", "years", "stack", "highlights", "do_not_claim", "writing_voice"];

export const LABELS = {
  full_name: "Full name",
  preferred_name: "Preferred name",
  email: "Email",
  phone: "Phone",
  location: "Location",
  timezone: "Timezone",
  work_authorization: "Work authorization",
  linkedin_url: "LinkedIn",
  github_url: "GitHub",
  titles: "Titles",
  locations: "Locations",
  seniority: "Seniority",
  domains: "Domains",
  remote: "Remote",
  must_haves: "Must haves",
  deal_breakers: "Deal breakers",
  headline: "Headline",
  years: "Years",
  stack: "Stack",
  highlights: "Highlights",
  do_not_claim: "Do not claim",
  writing_voice: "Writing voice",
};

const KEYS = ["full_name", ...STEP1.filter((key) => key !== "full_name"), ...STEP2, ...STEP3, "revision"];

export function emptyProfile() {
  return Object.fromEntries(KEYS.map((key) => [key, ""]));
}

export function fromYaml(text) {
  const values = emptyProfile();
  for (const line of String(text || "").split("\n")) {
    const cut = line.indexOf(":");
    if (cut < 1) continue;
    const key = line.slice(0, cut).trim();
    const value = line.slice(cut + 1).trim();
    if (key === "name") values.full_name = value;
    else if (key in values) values[key] = value;
  }
  return values;
}

export function toYaml(values) {
  const lines = [`name: ${values.full_name || ""}`];
  for (const key of KEYS) {
    if (key === "full_name") continue;
    lines.push(`${key}: ${(values[key] || "").replace(/\n/g, " / ")}`);
  }
  return `${lines.join("\n")}\n`;
}
