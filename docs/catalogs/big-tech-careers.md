# Big-company career sites

Direct portals. Discovery treats each req as a job file. Apply follows the company’s ATS. Outreach is careful: exec blasts at mega-caps are usually the wrong move unless the user asks.

| company | careers URL | typical ATS | dork seed |
| --- | --- | --- | --- |
| Amazon | https://www.amazon.jobs | amazon.jobs / Workday | `site:amazon.jobs` |
| Microsoft | https://jobs.careers.microsoft.com | Microsoft Careers | `site:jobs.careers.microsoft.com` |
| Google | https://www.google.com/about/careers | Google Careers | `site:careers.google.com` |
| Uber | https://www.uber.com/careers | Greenhouse-like / custom | `site:uber.com/careers` |
| Meta | https://www.metacareers.com | Meta Careers | `site:metacareers.com` |
| Apple | https://jobs.apple.com | Apple Jobs | `site:jobs.apple.com` |
| Netflix | https://jobs.netflix.com | Greenhouse | `site:jobs.netflix.com` |
| Stripe | https://stripe.com/jobs | Greenhouse | `site:stripe.com/jobs` |
| NVIDIA | NVIDIA Workday | Workday | `site:nvidia.wd5.myworkdayjobs.com` |
| OpenAI | https://openai.com/careers | Ashby | `site:openai.com/careers` |
| Anthropic | https://www.anthropic.com/careers | Ashby | `site:jobs.ashbyhq.com/anthropic` |
| Tesla | https://www.tesla.com/careers | Workday | `site:tesla.com/careers` |
| Airbnb | https://careers.airbnb.com | custom | `site:careers.airbnb.com` |
| Shopify | https://www.shopify.com/careers | Greenhouse | `site:www.shopify.com/careers` |
| Cloudflare | https://www.cloudflare.com/careers | Greenhouse | `site:boards.greenhouse.io/cloudflare` |
| Datadog | https://careers.datadoghq.com | Greenhouse | `site:careers.datadoghq.com` |
| Snowflake | https://careers.snowflake.com | Workday | `site:careers.snowflake.com` |
| Oracle | https://careers.oracle.com | Oracle Cloud | `site:careers.oracle.com` |
| Salesforce | https://careers.salesforce.com | custom | `site:careers.salesforce.com` |
| Adobe | https://careers.adobe.com | Workday | `site:careers.adobe.com` |
| Intel | https://jobs.intel.com | Workday | `site:jobs.intel.com` |
| IBM | https://www.ibm.com/careers | IBM | `site:ibm.com/careers` |
| Cisco | https://jobs.cisco.com | custom | `site:jobs.cisco.com` |
| Spotify | https://www.lifeatspotify.com | custom | `site:lifeatspotify.com` |
| Block | https://block.xyz/careers | Greenhouse | `site:block.xyz/careers` |
| Coinbase | https://www.coinbase.com/careers | Greenhouse | `site:boards.greenhouse.io/coinbase` |
| Palantir | https://www.palantir.com/careers | custom | `site:palantir.com/careers` |
| Anduril | https://www.anduril.com/careers | Ashby | `site:jobs.ashbyhq.com/anduril` |
| SpaceX | https://www.spacex.com/careers | custom | `site:spacex.com/careers` |

Add the companies the candidate actually wants. Do not pretend you searched fifty portals if you searched four.

## Packet extras for mega-caps

- Requisition / job id
- Team name if visible (AWS, Azure, Search, Maps, …)
- Location level (e.g. Amazon L5, Google L4) only if the posting says it
- Referral path: **teammate first**, not a cold CEO email
- `outreach.policy: teammates_and_recruiter` by default

## Referral-only sources

If a company has no public apply and only a “reach out” page, set:

```yaml
apply_kind: outreach_only
apply_packet:
  url: "https://company.com/careers"
  steps:
    - "No public req. Outreach owns this record."
```

Discovery still creates the job file so apply does not go hunting.
