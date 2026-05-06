# School District Budget Tracker — State-by-State Status

_Last updated: 2026-05-06_

**Coverage:** 37 states (+ DC) live, 37.3M / 44.8M K-12 students = **83.2% of US enrollment**.

**Every US state + DC has now been investigated.** 14 are deferred for various source-side blockers (interactive portals, captchas, IP blocks, JS-only dashboards, lagging publication).

This file is the running snapshot of which states are live, which are deferred, and what's next. Update it whenever an extractor lands, a state is deferred, or a follow-up is closed.

## Live extractors (sorted by enrollment)

| State | Enroll | Status | FY | Coverage | Topline ($) | Source |
|---|---:|---|:---:|---:|---:|---|
| TX | 5.49M | actual | 2025 | 1068/1069 (99.9%) | $70.8B | TEA PEIMS |
| CA | 4.26M | actual / **adopted** | 2025 / 2026 | 472/697 / 426/697 | $110.4B / $99.7B | SACS |
| FL | 2.83M | actual / **adopted** | 2025 / 2026 | 67/68 / 67/68 | $32.0B / $34.4B | FLDOE AFR + Summary Budget |
| GA | 1.73M | actual | 2025 | 184/192 (95.8%) | $24.5B | GOSA Rev/Exp |
| PA | 1.60M | **adopted** | 2026 | 490/545 (89.9%) | $39.7B | PDE GFB |
| OH | 1.55M | actual | 2025 | 606/646 (93.8%) | $25.1B | ODE Cupp |
| NC | 1.50M | actual ⚠️ | 2025 | 115/196 (58.7%) | $11.1B | NCDPI SPSF — state-funded only |
| MI | 1.34M | actual | 2025 | 603/663 (91.0%) | $22.1B | MDE Bulletin 1011 |
| VA | 1.26M | actual | 2025 | 101/130 (77.7%) | $22.0B | APA Comparative |
| IL | 1.12M | actual | 2024 | 380/397 (95.7%) | $19.6B | ISBE OEPP-PCTC |
| WA | 1.08M | actual | 2025 | 257/258 (99.6%) | $20.0B | OSPI F-196 |
| NJ | 1.05M | actual | 2024 | 231/265 (87.2%) | $30.9B | NJDOE TGES |
| IN | 1.01M | actual ⚠️ | 2024 | 290/335 (86.6%) | $13.3B | DUAB SCFI — traditional corps only |
| TN | 971k | actual | 2025 | 127/129 (98.4%) | $13.0B | TDOE ASR |
| MD | 891k | actual | 2024 | 24/24 (100%) | $17.5B | MSDE SFD |
| MA | 806k | actual | 2024 | 228/228 (100%) | $20.3B | DESE Profiles PPX |
| SC | 795k | actual | 2024 | 73/75 (97.3%) | $11.4B | SCDE In$ite |
| WI | 766k | actual | 2024 | 367/377 (97.3%) | $14.5B | DPI Comparative Cost |
| AL | 750k | actual | 2023 | 144/146 (98.6%) | $9.3B | ALSDE PPE |
| OK | 668k | actual | 2025 | 428/428 (100%) | $8.0B | OSDE OCAS |
| KY | 654k | actual | 2024 | 167/167 (100%) | $9.9B | KDE AFR R&E |
| UT | 650k | actual ⚠️ | 2024 | 41/82 (50.0%) | $9.3B | USBE AFR — districts only |
| LA | 609k | actual ⚠️ | 2024 | 69/87 (79.3%) | $9.8B | LDOE AFSR — traditional parishes only |
| OR | 543k | actual | 2024 | 179/184 (97.3%) | TBD | ODE Detailed District Expenditure |
| CT | ~525k | **adopted** | 2026 | 117/139 (84.2%) | $8.6B | CT OPM SODA API |
| IA | 504k | actual | 2024 | 325/325 (100%) | TBD | Iowa DE CAR |
| AR | 486k | actual | 2024 | 244/244 (100%) | TBD | ADE/DESE ASR |
| KS | ~470k | actual ⚠️ | 2025 | 284/286 (99.3%) | TBD | KS Open Gov per-pupil |
| MS | ~440k | actual | 2024 | 137/137 (100%) | TBD | MDE Sup Annual Report |
| ID | 301k | actual | 2024 | 136/137 (99.3%) | TBD | ISDE 20-Year R&E |
| HI | 167k | actual / **adopted** | 2025 / 2027 | 1/1 / 1/1 (100%) | $3.93B / $2.86B | HIDOE AFSA + DBF Budget-in-Brief (biennial) |
| ME | 160k | actual ⚠️ | 2025 | 97/177 (54.8%) | TBD | ME DOE — RSU/MSAD granularity mismatch |
| SD | 141k | actual | 2025 | 148/148 (100%) | TBD | SD DOE All Expenditures |
| ND | 118k | actual | 2024 | 143/143 (100%) | TBD | NDDPI FinFacts PDF |
| VT | 71k | actual | 2024 | 80/80 (100%) | TBD | VT AOE Cohort Spending |
| DC | 67k | actual | 2024 | 6/6 (100%) | TBD | OSSE Report Card Finance |
| MT | 21k | actual | 2025 | 64/64 (100%) | TBD | OPI School Expenditures |

## Deferred (14 states, ~8.0M enrollment)

| State | Enroll | Reason | Path forward |
|---|---:|---|---|
| NY | 2.36M | NYSED has no bulk financial feed | FOIA / Chrome-MCP |
| MO | 869k | DESE ASBR per-district ASP.NET postback only | Chrome-MCP / FOIA |
| CO | 865k | CDE rate-limited our IP | Re-attempt from different network |
| MN | 836k | MDE behind Perfdrive captcha | Chrome-MCP / FOIA |
| AZ | 650k | ADE Akamai-blocked | Chrome-MCP / FOIA |
| NV | 483k | per-LEA PDFs unpredictable URLs | Chrome-MCP / FOIA |
| NE | 330k | sfos.education.ne.gov ASP.NET per-district interactive | Chrome-MCP postback automation |
| NM | 295k | openbooks.ped.nm.gov reCAPTCHA-gated | Chrome-MCP through reCAPTCHA |
| WV | ~242k | wvde.us Drupal Access Denied | Chrome-MCP against OpenGov |
| AK | 129k | No per-district bulk expenditure file published | FOIA DEED |
| RI | 127k | datacenter.ride.ri.gov Tableau-only | Chrome-MCP / FOIA |
| DE | 124k | EDSTATS PDF lags 2 years | Wait for fresher publication |
| NH | 119k | education.nh.gov Akamai-blocked (same as AZ) | Chrome-MCP / FOIA |
| WY | 89k | edu.wyoming.gov JS-rendered, no bulk download | Chrome-MCP / FOIA |

## All states + DC accounted for

51 jurisdictions = 37 live + 14 deferred. Coverage milestone: every state has been investigated and has a documented status.

## Adopted-budget pipelines (5 states)

Most states publish actuals (post-audit), not adopted budgets. These 5 have a real-time adopted-budget pipeline:

| State | Source | Frequency | Notes |
|---|---|---|---|
| FL | FLDOE Summary Budget portal (TRIM) | Per-district, near-real-time | 67/68 LEAs FY26 adopted captured |
| CA | SACS Data Viewer Budget filings | Per-district, post-Aug 15 county review | 426/697 LEAs FY26 adopted |
| PA | PDE General Fund Budget bulk Excel | Annual, ~Sept after Jun 30 adoption | 490/545 LEAs FY26 adopted |
| CT | CT OPM Adopted Municipal Budget SoQL API | Real-time per-town | 117/139 LEAs FY26 adopted (date_budget_adopted recorded) |
| HI | HI DBF Budget-in-Brief PDF | Biennial via legislative act | 1/1 LEA FY27 adopted ($2.86B) — *only state with FY27 budget data so far* |

For VT/NH/IA (deadlines also passed for FY27): publication doesn't follow adoption — VT publishes per-district file post-audit (~Jan 2028); NH site Akamai-blocked; IA DOM API auth-required. Documented in [PLAN.md](../PLAN.md).

## Open follow-ups (existing extractors)

- **NC LGC all-funds** — close state-funded-only gap (~40% of operating)
- **UT charters** — LeaNbr → A-code crosswalk for 15 skipped charter LEAs
- **VA joint-division override** — 8 unmatched joint city-county divisions
- **PA AFR** — close PA actuals gap
- **IL Form 50-39** — close IL adopted-budget gap
- **CA charter-via-Alt-Form** — sibling extractor for ~30% gap
- **IN charters** — 45 IN charter LEAs not in SCFI
- **LA Type 2 charters** — 18 LA charter LEAs aggregated as '4-Type 2'
- **ME RSU/MSAD consolidation** — bridge per-municipality SAUs to RSU groupings
- **MI/OH/GA/TX adopted-budget** — would need per-district scraping
- **Annual `KNOWN_FILE_URLS` refresh** — IN/WI/MD/SC/AL/LA/IA/MS/HI/ID/SD/ND/VT/DC/MT all need annual URL bumps
- **AL FY24 PDF** — refresh when ALSDE publishes
- **KS reconstruction precision** — investigate using KSDE-published weighted FTE
- **DC charters not in master** — 63 charter LEAs in OSSE file but not in master operating-LEA set

## Reattack candidates (deferred but data quality is high once unblocked)

Highest-value targets if a Chrome-MCP automation harness gets built:
1. **NY (2.36M)** — would push us from 83.2% → 88.5% coverage
2. **MO (869k)** — DESE ASBR data is comprehensive once postback automated
3. **CO (865k)** — code is verified; just need network unblock
4. **MN (836k)** — MFR has rich per-district data once captcha cleared
5. **AZ (650k)** — Auditor's Tableau dashboards have detailed per-district data
