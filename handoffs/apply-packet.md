# Apply packet

Discovery fills this. Apply follows it. If a field is unknown, write `unknown` — do not omit.

Copy the YAML block into `apply_packet` on the job file.

```yaml
apply_packet:
  url: ""                  # exact submit URL, not a Google card
  listing_url: ""          # if different from submit
  ats: ""                  # greenhouse | lever | ashby | workday | linkedin | indeed | other
  apply_kind: ats          # ats | linkedin_easy_apply | indeed | network | outreach_only
  account: ""              # which email / which site login
  req_id: ""
  documents:
    - assets/resume/resume-primary.pdf
  questions:
    - ""                   # visible screening questions
  steps:
    - "Open url"
    - "..."
  why_shortlisted: |
    three lines of evidence
  compensation_hint: ""
  deadline: ""
  do_not_apply_yet: true   # apply role flips this when claiming
```

Done means: a cold apply bot with only this file + candidate.yaml + the PDF can submit.
