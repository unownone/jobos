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
  location: "Home base",
  timezone: "Timezone",
  work_authorization: "Work authorization",
  linkedin_url: "LinkedIn",
  github_url: "GitHub",
  titles: "Target titles",
  locations: "Target locations",
  seniority: "Seniority",
  domains: "Domains",
  remote: "Remote preference",
  must_haves: "Must haves",
  deal_breakers: "Deal breakers",
  headline: "Headline",
  years: "Years of experience",
  stack: "Stack",
  highlights: "Highlights",
  do_not_claim: "Do not claim",
  writing_voice: "Writing voice",
};

/** Short nudges shown under each field. Keep truthful — never invent experience. */
export const HINTS: Record<Exclude<ProfileKey, "revision">, string> = {
  full_name: "Legal name for applications. Required.",
  preferred_name: "What recruiters should call you.",
  email: "The inbox you check. Required.",
  phone: "Optional. Include country code.",
  location: "City you are based in, e.g. Bengaluru, India.",
  timezone: "Used for scheduling. Search or pick your system zone.",
  work_authorization: "Citizenship / visa reality. Be specific.",
  linkedin_url: "Full profile URL.",
  github_url: "Full profile URL.",
  titles: "Comma-separated roles you want, e.g. Staff Engineer, Senior Backend.",
  locations: "Where you will work: Remote, Bengaluru, SF — comma-separated. Required.",
  seniority: "e.g. senior, staff, principal.",
  domains: "e.g. developer tools, infra, AI products.",
  remote: "required, hybrid, or onsite-ok.",
  must_haves: "Non-negotiables for the role or company.",
  deal_breakers: "Things that make you walk away.",
  headline: "One line agents reuse in outreach.",
  years: "Whole number of years shipping software.",
  stack: "Comma-separated languages and systems you actually use.",
  highlights: "Proof bullets only. No invented metrics.",
  do_not_claim: "Topics agents must never invent for you.",
  writing_voice: "Tone for emails and notes. Short and direct works best.",
};

export const STEP_META = [
  { n: 1, title: "Identity", blurb: "Who you are and how to reach you." },
  { n: 2, title: "Targets", blurb: "Titles and places you want agents to hunt." },
  { n: 3, title: "Proof", blurb: "Truthful highlights agents may reuse." },
  { n: 4, title: "Resume", blurb: "PDF stored in Hub object storage for outreach." },
] as const;

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

export function systemTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function allTimezones(): string[] {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  if (typeof intl.supportedValuesOf === "function") {
    return intl.supportedValuesOf("timeZone");
  }
  return [
    "UTC",
    "Asia/Kolkata",
    "Asia/Dubai",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Australia/Sydney",
  ];
}
