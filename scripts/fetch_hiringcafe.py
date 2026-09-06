#!/usr/bin/env python3
"""Fetch Hiring Cafe (hiringcafe.com) public listing pages.

Hiring Cafe is the Reddit/Blind-shared job search engine (hiring.cafe 308s here).
Public listing HTML embeds a Next.js `__NEXT_DATA__` island. This script reads
that island — the same approach as maazghani/hiring-mcp.cafe — without a browser.
Cloudflare may 403 datacenter IPs; then use Exa crawl / WebFetch of the same URL.
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from typing import Any

BASE = "https://hiringcafe.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TIMEOUT = 20

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
JOB_HREF_RE = re.compile(
    r'href="(/job/[^"?#]+|https://hiring(?:cafe)?\.com/job/[^"?#]+|https://hiring\.cafe/job/[^"?#]+)"'
)


def slugify(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower().strip())
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_)
    return slug.strip("-")


def listing_url(query: str | None, location: str | None) -> str:
    q = slugify(query) if query else ""
    loc = slugify(location) if location else ""
    if q and loc:
        path = f"/jobs/{q}-{loc}"
    elif loc:
        path = f"/jobs/{loc}"
    elif q:
        path = f"/jobs/{q}"
    else:
        raise SystemExit("need --query and/or --location, or --url")
    return BASE + path


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code in {401, 403, 429}:
            hint = (
                " Cloudflare often challenges datacenter IPs. Fall back to Exa "
                "`crawling_exa` or WebFetch of the same public URL, then parse "
                "__NEXT_DATA__. Do not invent jobs."
            )
        raise SystemExit(f"HTTP {exc.code} for {url}.{hint}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"fetch failed for {url}: {exc}") from exc


def extract_next_data(page: str) -> dict[str, Any] | None:
    match = NEXT_DATA_RE.search(page)
    if not match:
        return None
    raw = htmlmod.unescape(match.group(1))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def job_url_map(page: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for href in JOB_HREF_RE.findall(page):
        abs_url = href if href.startswith("http") else BASE + href
        slug = abs_url.split("/job/", 1)[-1].split("?", 1)[0]
        found[slug] = abs_url
        req_id = slug.rsplit("-", 1)[-1]
        if req_id:
            found[req_id] = abs_url
    return found


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _salary(v5: dict[str, Any]) -> str | None:
    currency = v5.get("listed_compensation_currency") or "USD"
    freq_raw = str(v5.get("listed_compensation_frequency") or "").lower()
    pairs = [
        ("yearly", v5.get("yearly_min_compensation"), v5.get("yearly_max_compensation")),
        ("monthly", v5.get("monthly_min_compensation"), v5.get("monthly_max_compensation")),
        ("weekly", v5.get("weekly_min_compensation"), v5.get("weekly_max_compensation")),
        ("hourly", v5.get("hourly_min_compensation"), v5.get("hourly_max_compensation")),
    ]
    ordered = sorted(pairs, key=lambda p: 0 if p[0] == freq_raw else 1)
    for freq, lo, hi in ordered:
        if not lo and not hi:
            continue
        unit = "/hr" if freq == "hourly" else "/yr" if freq == "yearly" else f"/{freq}"
        if lo and hi:
            return f"{currency} {lo}–{hi}{unit}"
        return f"{currency} {lo or hi}{unit}"
    return None


def hit_to_row(hit: dict[str, Any], urls: dict[str, str]) -> dict[str, Any] | None:
    v5 = hit.get("v5_processed_job_data") or {}
    ji = hit.get("job_information") or {}
    title = _clean(ji.get("title") or v5.get("core_job_title") or hit.get("job_title"))
    if not title:
        return None
    req_id = hit.get("requisition_id")
    url = (
        (req_id and urls.get(str(req_id)))
        or hit.get("apply_url")
        or hit.get("hc_apply_url")
    )
    if not url:
        slug = hit.get("hc_pinned_slug")
        if slug:
            url = f"{BASE}/job/{slug}"
    if not url:
        return None
    tools = v5.get("technical_tools") if isinstance(v5.get("technical_tools"), list) else []
    return {
        "title": title,
        "company": _clean(v5.get("company_name") or hit.get("hc_group")),
        "location": _clean(v5.get("formatted_workplace_location")),
        "salary": _salary(v5) if isinstance(v5, dict) else None,
        "workplace_type": _clean(v5.get("workplace_type")),
        "hiring_cafe_url": url if str(url).startswith("http") else BASE + str(url),
        "apply_url": _clean(hit.get("apply_url") or hit.get("hc_apply_url")),
        "skills": [str(s) for s in tools[:15]],
        "source": "hiringcafe",
    }


def search(url: str) -> list[dict[str, Any]]:
    page = fetch_html(url)
    nxt = extract_next_data(page)
    if not nxt:
        raise SystemExit(
            f"no __NEXT_DATA__ on {url} — page layout may have changed; "
            "fall back to WebFetch of the same URL"
        )
    hits = (((nxt.get("props") or {}).get("pageProps") or {}).get("ssrHits")) or []
    urls = job_url_map(page)
    rows: list[dict[str, Any]] = []
    for hit in hits:
        if isinstance(hit, dict):
            row = hit_to_row(hit, urls)
            if row:
                rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query")
    parser.add_argument("--location")
    parser.add_argument("--url", help="Full hiringcafe.com listing URL")
    parser.add_argument("--job-url", help="Single /job/ detail URL (prints NEXT_DATA job blob)")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    if args.job_url:
        page = fetch_html(args.job_url)
        nxt = extract_next_data(page)
        job = (((nxt or {}).get("props") or {}).get("pageProps") or {}).get("job")
        json.dump(job or {"error": "no job in NEXT_DATA", "url": args.job_url}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    url = args.url or listing_url(args.query, args.location)
    rows = search(url)[: args.limit]
    json.dump({"source": "hiringcafe.com", "listing_url": url, "count": len(rows), "jobs": rows}, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
