export const STEP1 = [
  "full_name",
  "preferred_name",
  "email",
  "phone",
  "location",
  "timezone",
  "work_authorization",
  "linkedin_url",
  "github_url",
] as const;

export const STEP2 = [
  "titles",
  "locations",
  "seniority",
  "domains",
  "remote",
  "must_haves",
  "deal_breakers",
] as const;

export const STEP3 = ["headline", "years", "stack", "highlights", "do_not_claim", "writing_voice"] as const;

export type ProfileKey =
  | (typeof STEP1)[number]
  | (typeof STEP2)[number]
  | (typeof STEP3)[number]
  | "revision";

export type ProfileValues = Record<ProfileKey, string>;

export const LABELS: Record<Exclude<ProfileKey, "revision">, string> = {
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

const KEYS: ProfileKey[] = [
  "full_name",
  ...STEP1.filter((key) => key !== "full_name"),
  ...STEP2,
  ...STEP3,
  "revision",
];

export function emptyProfile(): ProfileValues {
  return Object.fromEntries(KEYS.map((key) => [key, ""])) as ProfileValues;
}

export function fromYaml(text: string): ProfileValues {
  const values = emptyProfile();
  for (const line of String(text || "").split("\n")) {
    const cut = line.indexOf(":");
    if (cut < 1) continue;
    const key = line.slice(0, cut).trim();
    const value = line.slice(cut + 1).trim();
    if (key === "name") values.full_name = value;
    else if (key in values) values[key as ProfileKey] = value;
  }
  return values;
}

export function toYaml(values: ProfileValues): string {
  const lines = [`name: ${values.full_name || ""}`];
  for (const key of KEYS) {
    if (key === "full_name") continue;
    lines.push(`${key}: ${(values[key] || "").replace(/\n/g, " / ")}`);
  }
  return `${lines.join("\n")}\n`;
}
