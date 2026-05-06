# School District Budget Tracker — State-by-State Status

_Last updated: 2026-05-06_

**Coverage:** 16 states live, 27.7M / 44.8M K-12 students = **61.8% of US enrollment**.

This file is the running snapshot of which states are live, which are deferred, and what's next. Update it whenever an extractor lands, a state is deferred, or a follow-up is closed.

## Live extractors (sorted by enrollment)

| State | Enroll | Status | FY | Coverage | Topline ($) | Source |
|---|---:|---|:---:|---:|---:|---|
| TX | 5.49M | actual | 2025 | 1068/1069 (99.9%) | $70.8B | TEA PEIMS Summarized Financial Data |
| CA | 4.26M | actual / **adopted** | 2025 / 2026 | 472/697 (67.7%) / 426/697 (61.1%) | $110.4B / $99.7B | SACS unaudited actuals + SACS Data Viewer BS1 |
| FL | 2.83M | actual / **adopted** | 2025 / 2026 | 67/68 (98.5%) / 67/68 (98.5%) | $32.0B / $34.4B | FLDOE AFR + Summary Budget portal |
| GA | 1.73M | actual | 2025 | 184/192 (95.8%) | $24.5B | GOSA Revenues_and_Expenditures CSV |
| PA | 1.60M | **adopted** | 2026 | 490/545 (89.9%) | $39.7B | PDE General Fund Budget bulk Excel |
| OH | 1.55M | actual | 2025 | 606/646 (93.8%) | $25.1B | ODE Cupp Report (ADM × OEPP) |
| NC | 1.50M | actual ⚠️ | 2025 | 115/196 (58.7%) | $11.1B | NCDPI SPSF — **state-funded only** |
| MI | 1.34M | actual | 2025 | 603/663 (91.0%) | $22.1B | MDE Bulletin 1011 Excel |
| VA | 1.26M | actual | 2025 | 101/130 (77.7%) | $22.0B | APA Comparative Report Exhibit C |
| IL | 1.12M | actual | 2024 | 380/397 (95.7%) | $19.6B | ISBE OEPP-PCTC bulk Excel |
| WA | 1.08M | actual | 2025 | 257/258 (99.6%) | $20.0B | OSPI F-196 10-year XLSX |
| NJ | 1.05M | actual | 2024 | 231/265 (87.2%) | $30.9B | NJDOE TGES Detail XLSX |
| TN | 971k | actual | 2025 | 127/129 (98.4%) | $13.0B | TDOE Annual Statistical Report Table 51 |
| MA | 806k | actual | 2024 | 228/228 (100%) | $20.3B | DESE Profiles statereport PPX |
| UT | 650k | actual ⚠️ | 2024 | 41/82 (50.0%) | $9.3B | USBE AFR — **districts only (charters TBD)** |
| CT | ~525k | **adopted** | 2026 | 117/139 (84.2%) | $8.6B | CT OPM SODA API (real-time) |

## Deferred (5 states, ~6.1M enrollment)

| State | Enroll | Reason | Path forward |
|---|---:|---|---|
| NY | 2.36M | NYSED has no bulk financial feed; OSC Open Book retired; ST-3 not machine-readable | FOIA NYSED/OSC, or Chrome-MCP per-district BoardDocs scraper |
| AZ | 650k | Auditor PDFs only; ADE Akamai-blocks our IP/UA | Chrome-MCP against Auditor's Tableau, or FOIA |
| MO | 869k | DESE ASBR PublicView is per-district ASP.NET `__doPostBack` (~520 districts × FY); no bulk export; MCDS login-only | Chrome-MCP postback automation, FOIA `finadmgov@dese.mo.gov`, or VIEWSTATE scraper |
| MN | 836k | MDE MFR / Financial Profiles behind Perfdrive captcha; only static publication is the blank ED-00110-48 template | Chrome-MCP through captcha, FOIA `mde.ufars-accounting@state.mn.us`, or per-district publication scrape (§ 123B.10) |
| CO | 865k | **Different wall:** data is clean (`Org_Spending_Funding` sheet verified) — CDE rate-limited our source IP mid-investigation | Re-attempt from different network/proxy, wait for rate-limit window, or email CDE for whitelisting |

## Next up by enrollment (not yet attempted)

| State | Enroll | Priority |
|---|---:|---|
| IN | 1.01M | next-largest greenfield |
| MD | 891k | |
| SC | 795k | |
| WI | 766k | |
| AL | 750k | |
| OK | 668k | |
| KY | 654k | |
| LA | 609k | |

## Open follow-ups (existing extractors)

- **NC LGC all-funds** — close state-funded-only gap (~40% of operating)
- **UT charters** — LeaNbr → A-code crosswalk for the 15 skipped charter LEAs
- **VA joint-division override** — 8 unmatched joint city-county divisions (Williamsburg-James City etc.)
- **PA AFR** — close PA actuals gap (PDE doesn't publish from same landing page)
- **IL Form 50-39** — close IL adopted-budget gap
- **CA charter-via-Alt-Form** — sibling extractor for the ~30% gap
- **MI/OH/GA/TX adopted-budget** — would need per-district scraping (no bulk feed)
