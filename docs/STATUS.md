# School District Budget Tracker — State-by-State Status

_Last updated: 2026-05-06_

**Coverage:** 29 states live, 36.3M / 44.8M K-12 students = **80.9% of US enrollment**.

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
| IN | 1.01M | actual ⚠️ | 2024 | 290/335 (86.6%) | $13.3B | DUAB SCFI — **traditional corps only (charters TBD)** |
| TN | 971k | actual | 2025 | 127/129 (98.4%) | $13.0B | TDOE Annual Statistical Report Table 51 |
| MD | 891k | actual | 2024 | 24/24 (100%) | $17.5B | MSDE Selected Financial Data Part 2 PDF |
| MA | 806k | actual | 2024 | 228/228 (100%) | $20.3B | DESE Profiles statereport PPX |
| SC | 795k | actual | 2024 | 73/75 (97.3%) | $11.4B | SCDE In$ite per-district PDFs |
| WI | 766k | actual | 2024 | 367/377 (97.3%) | $14.5B | DPI Comparative Cost Per Member XLSX |
| AL | 750k | actual | 2023 | 144/146 (98.6%) | $9.3B | ALSDE System Level PPE PDF |
| OK | 668k | actual | 2025 | 428/428 (100%) | $8.0B | OSDE OCAS (With Exclusions) XLSX |
| KY | 654k | actual | 2024 | 167/167 (100%) | $9.9B | KDE AFR Revenues and Expenditures XLSX |
| UT | 650k | actual ⚠️ | 2024 | 41/82 (50.0%) | $9.3B | USBE AFR — **districts only (charters TBD)** |
| LA | 609k | actual ⚠️ | 2024 | 69/87 (79.3%) | $9.8B | LDOE AFSR Item 9 — **traditional parishes (Type 2 charters TBD)** |
| OR | 543k | actual | 2024 | 179/184 (97.3%) | TBD | ODE Detailed District Expenditure XLSX |
| CT | ~525k | **adopted** | 2026 | 117/139 (84.2%) | $8.6B | CT OPM SODA API (real-time) |
| IA | 504k | actual | 2024 | 325/325 (100%) | TBD | Iowa DE Certified Annual Report XLSX |
| AR | 486k | actual | 2024 | 244/244 (100%) | TBD | ADE/DESE Annual Statistical Report PDF |
| KS | ~470k | actual ⚠️ | 2025 | 284/286 (99.3%) | TBD | KS Open Gov per-pupil CSV (KSDE CPFS source); per-pupil × enrollment |
| MS | ~440k | actual | 2024 | 137/137 (100%) | TBD | MDE Sup Annual Report Functional Area XLSX |

## Deferred (7 states, ~7.6M enrollment)

| State | Enroll | Reason | Path forward |
|---|---:|---|---|
| NY | 2.36M | NYSED has no bulk financial feed; OSC Open Book retired; ST-3 not machine-readable | FOIA NYSED/OSC, or Chrome-MCP per-district BoardDocs scraper |
| MO | 869k | DESE ASBR PublicView is per-district ASP.NET `__doPostBack` (~520 districts × FY); no bulk export; MCDS login-only | Chrome-MCP postback automation, FOIA `finadmgov@dese.mo.gov`, or VIEWSTATE scraper |
| CO | 865k | CDE rate-limited our source IP mid-investigation (data path is clean) | Re-attempt from different network/proxy, or wait for rate-limit window |
| MN | 836k | MDE MFR / Financial Profiles behind Perfdrive captcha; only static publication is the blank ED-00110-48 template | Chrome-MCP through captcha, FOIA `mde.ufars-accounting@state.mn.us` |
| NV | 483k | Statewide PDF is aggregate-only; per-LEA PDFs exist but URL slugs are unpredictable; no directory listing | Chrome-MCP against Report Card, or FOIA NDE for unfiltered NRS template |
| AZ | 650k | Auditor PDFs only; ADE Akamai-blocks our IP/UA | Chrome-MCP against Auditor's Tableau, or FOIA |
| WV | ~242k | WVDE finance pages return Drupal Access Denied; OpenGov is JS-only SPA; WVEIS not public | Chrome-MCP against OpenGov transparency portal, or FOIA WVDE Office of School Finance |

## Next up by enrollment (not yet attempted)

| State | Enroll | Priority |
|---|---:|---|
| NM | ~325k | next-largest greenfield |
| ID | ~315k | |
| NE | ~310k | |
| ME | ~175k | |
| NH | ~170k | |
| HI | ~170k | (single statewide district — special case) |
| RI | ~140k | |
| MT | ~145k | |
| DE | ~140k | |
| ND | ~115k | |
| SD | ~140k | |
| AK | ~130k | |
| VT | ~85k | |
| WY | ~95k | |
| DC | ~95k | (single district + many charters) |

## Open follow-ups (existing extractors)

- **NC LGC all-funds** — close state-funded-only gap (~40% of operating)
- **UT charters** — LeaNbr → A-code crosswalk for the 15 skipped charter LEAs
- **VA joint-division override** — 8 unmatched joint city-county divisions (Williamsburg-James City etc.)
- **PA AFR** — close PA actuals gap (PDE doesn't publish from same landing page)
- **IL Form 50-39** — close IL adopted-budget gap
- **CA charter-via-Alt-Form** — sibling extractor for the ~30% gap
- **IN charters** — 45 IN charter LEAs not in SCFI (file via different system)
- **LA Type 2 charters** — 18 LA charter LEAs aggregated as '4-Type 2' in AFSR
- **MI/OH/GA/TX adopted-budget** — would need per-district scraping (no bulk feed)
- **IN/WI/MD/SC/AL/LA/IA/MS URL refresh** — annual `KNOWN_FILE_URLS` bumps when DOEs publish next FY (URLs have date / release-year / media-id suffixes)
- **AL FY24 PDF** — refresh when ALSDE publishes (lags ~1 year vs Jul-Jun states)
- **KS reconstruction precision** — investigate using KSDE-published weighted FTE (instead of master enrollment_fy25) for tighter reconstruction
