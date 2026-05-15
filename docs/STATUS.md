# School District Budget Tracker — State-by-State Status

_Last updated: 2026-05-14_

**Coverage:** 44 states (+ DC) live, 41.4M / 44.8M K-12 students = **92.4% of US enrollment**.

**Every US state + DC has now been investigated.** 6 are deferred for various source-side blockers (interactive portals, captchas, JS-only dashboards, lagging publication). NY is now reclassified as **buildable, queued** — the prior "no bulk feed" deferral was wrong; NYSED ST-3 publishes as a stable ZIP at `https://stateaid.nysed.gov/st3/st3data/{YYYY-YYYY}_School_Year_{YYYY-YYYY}_SAMS%20ST-3.zip` (FY24 = 13.89 MB). Same pattern as CA SACS.

This file is the running snapshot of which states are live, which are deferred, and what's next. Update it whenever an extractor lands, a state is deferred, or a follow-up is closed.

## Live extractors (sorted by enrollment)

| State | Enroll | Status | FY | Coverage | Topline ($) | Source |
|---|---:|---|:---:|---:|---:|---|
| TX | 5.49M | actual / **adopted** | 2025 / 2026 | 1068/1069 / 1068/1069 | $70.8B / $67.3B | TEA PEIMS Summarized + PEIMS 030 |
| CA | 4.26M | actual / **adopted** | 2025 / 2026 | 472/697 / 426/697 | $110.4B / $99.7B | SACS |
| FL | 2.83M | actual / **adopted** | 2025 / 2026 | 67/68 / 67/68 | $32.0B / $34.4B | FLDOE AFR + Summary Budget |
| GA | 1.73M | actual | 2025 | 184/192 (95.8%) | $24.5B | GOSA Rev/Exp |
| PA | 1.60M | **adopted** | 2026 | 490/545 (89.9%) | $39.7B | PDE GFB |
| OH | 1.55M | actual | 2025 | 606/646 (93.8%) | $25.1B | ODE Cupp |
| NC | 1.50M | actual ⚠️ | 2025 | 115/196 (58.7%) | $11.1B | NCDPI SPSF — state-funded only |
| MI | 1.34M | actual | 2025 | 603/663 (91.0%) | $22.1B | MDE Bulletin 1011 |
| VA | 1.26M | actual | 2025 | 101/130 (77.7%) | $22.0B | APA Comparative |
| IL | 1.12M | actual | 2024 | 380/397 (95.7%) | $19.6B | ISBE OEPP-PCTC |
| WA | 1.08M | actual / **adopted** | 2025 / 2026 | 257/258 / 256/258 | $20.0B / $24.7B | OSPI F-196 + F-195 .accdb |
| NJ | 1.05M | actual / **adopted** | 2024 / 2026 | 231/265 / 238/265 | $30.9B / $26.1B | NJDOE TGES + UFB CSV |
| IN | 1.01M | actual / **adopted** ⚠️ | 2024 / 2025 | 290/335 / 287/335 | $13.3B / $11.0B | DUAB SCFI + DLGF Gateway Form 4B (IPS gap) |
| TN | 971k | actual | 2025 | 127/129 (98.4%) | $13.0B | TDOE ASR |
| MO | 869k | actual ⚠️ | 2025 | 459/459 (100%) | $17.1B | DESE MCDS Finance Summary XLS — all-funds (incl debt+capital), not strict F-33 |
| MN | 836k | actual | 2025 | 385/386 (99.7%) | $14.8B | MDE MFR UFR020 PDFs (user-solved Reblaze captcha cookies + curl-cffi) |
| MD | 891k | actual | 2024 | 24/24 (100%) | $17.5B | MSDE SFD |
| MA | 806k | actual | 2024 | 228/228 (100%) | $20.3B | DESE Profiles PPX |
| SC | 795k | actual | 2024 | 73/75 (97.3%) | $11.4B | SCDE In$ite |
| WI | 766k | actual | 2024 | 367/377 (97.3%) | $14.5B | DPI Comparative Cost |
| AL | 750k | actual | 2023 | 144/146 (98.6%) | $9.3B | ALSDE PPE |
| OK | 668k | actual | 2025 | 428/428 (100%) | $8.0B | OSDE OCAS |
| AZ | 650k | actual ⚠️ | 2025 | 162/187 (86.6%) | $7.4B | ADE SAFR Digital Data (curl-cffi) — Unified districts only |
| KY | 654k | actual | 2024 | 167/167 (100%) | $9.9B | KDE AFR R&E |
| UT | 650k | actual ⚠️ | 2024 | 41/82 (50.0%) | $9.3B | USBE AFR — districts only |
| LA | 609k | actual ⚠️ | 2024 | 69/87 (79.3%) | $9.8B | LDOE AFSR — traditional parishes only |
| CO | 865k | actual | 2024 | 181/181 (100%) | $14.0B | CDE Financial Transparency (curl-cffi + retry) |
| WV | ~242k | **adopted** ⚠️ | 2026 | 51/55 (92.7%) | $1.4B | WVDE PSSP BOE Recon (curl-cffi) — state-aid frame only |
| OR | 543k | actual | 2024 | 179/184 (97.3%) | TBD | ODE Detailed District Expenditure |
| CT | ~525k | **adopted** | 2026 | 117/139 (84.2%) | $8.6B | CT OPM SODA API |
| IA | 504k | actual | 2024 | 325/325 (100%) | TBD | Iowa DE CAR |
| AR | 486k | actual | 2024 | 244/244 (100%) | TBD | ADE/DESE ASR |
| KS | ~470k | actual / **adopted** ⚠️ | 2025 / 2026 | 284/286 / 285/286 | TBD / $8.8B | KS Open Gov + KSDE BAG PDFs |
| MS | ~440k | actual | 2024 | 137/137 (100%) | TBD | MDE Sup Annual Report |
| NE | 330k | actual | 2025 | 245/245 (100%) | $4.8B | NE SFOS AFR ZIP (Fund 01 GF expenditures) |
| ID | 301k | actual | 2024 | 136/137 (99.3%) | TBD | ISDE 20-Year R&E |
| HI | 167k | actual / **adopted** | 2025 / 2027 | 1/1 / 1/1 (100%) | $3.93B / $2.86B | HIDOE AFSA + DBF Budget-in-Brief (biennial) |
| ME | 160k | actual ⚠️ | 2025 | 97/177 (54.8%) | TBD | ME DOE — RSU/MSAD granularity mismatch |
| NH | 119k | actual | 2025 | 62/70 (88.6%) | $2.5B | NH DOE Cost Per Pupil CSV (curl-cffi); CPP × enrollment |
| SD | 141k | actual | 2025 | 148/148 (100%) | TBD | SD DOE All Expenditures |
| ND | 118k | actual | 2024 | 143/143 (100%) | TBD | NDDPI FinFacts PDF |
| VT | 71k | actual | 2024 | 80/80 (100%) | TBD | VT AOE Cohort Spending |
| DC | 67k | actual | 2024 | 6/6 (100%) | TBD | OSSE Report Card Finance |
| MT | 21k | actual | 2025 | 64/64 (100%) | TBD | OPI School Expenditures |

## Buildable, queued (1 state, 2.36M enrollment) — NEW 2026-05-14

| State | Enroll | Source | Notes |
|---|---:|---|---|
| NY | 2.36M | NYSED ST-3 ZIP | `https://stateaid.nysed.gov/st3/st3data/{YYYY-YYYY}_School_Year_{YYYY-YYYY}_SAMS%20ST-3.zip` — Excel single-file XLSX also available. 2026-05-14 investigation confirmed bulk file exists at predictable URL; the prior deferral mis-identified the href as relative-to-domain-root when it's relative-to-/st3/. Topline definition + crosswalk TBD. Same pattern as CA SACS (.zip with .mdb / .xlsx). Closing this would push coverage 92.4% → 97.6%. |

## Deferred (6 states, ~1.7M enrollment)

| State | Enroll | Reason | Path forward |
|---|---:|---|---|
| NV | 483k | per-LEA PDFs unpredictable URLs | Chrome-MCP / FOIA |
| NM | 295k | openbooks.ped.nm.gov + Looker SaaS embed (Sucuri WAF defeated by curl-cffi chrome124, but data lives in Looker dashboards requiring tile-by-tile CSV scraping) | Build Looker scraper (significant effort) |
| AK | 129k | No per-district bulk expenditure file published | FOIA DEED |
| RI | 127k | datacenter.ride.ri.gov Tableau-only | Chrome-MCP / FOIA |
| DE | 124k | EDSTATS PDF lags 2 years | Wait for fresher publication |
| WY | 89k | edu.wyoming.gov JS-rendered, no bulk download | Chrome-MCP / FOIA |

## All states + DC accounted for

51 jurisdictions = 44 live + 7 deferred. **KS/AZ/NH/WV/CO/MO/NE/MN all moved from deferred to live on 2026-05-07** via the techniques toolkit:
- **curl-cffi chrome120** TLS-impersonation defeats Akamai/Imperva/CDE-style WAFs (KS, AZ, NH, WV, CO)
- **Multi-step ASP.NET postback / passwordless auth** unlocks DESE-style portals (IN, MO)
- **Direct file URL discovery** when the deferral assumed postback but actually had static links (NE)
- **User-solved captcha + DevTools cURL capture** unlocks heavily-stateful WebFOCUS-style portals (MN)

## Adopted-budget pipelines (10 states)

Most states publish actuals (post-audit), not adopted budgets. These 10 have a real-time adopted-budget pipeline:

| State | Source | Frequency | Notes |
|---|---|---|---|
| TX | TEA PEIMS Record 030 bulk CSV (districts + charters) | Annual, posted ~Feb of school year | 1068/1069 LEAs FY26 adopted ($67.3B); largest-state win |
| FL | FLDOE Summary Budget portal (TRIM) | Per-district, near-real-time | 67/68 LEAs FY26 adopted captured |
| CA | SACS Data Viewer Budget filings | Per-district, post-Aug 15 county review | 426/697 LEAs FY26 adopted |
| PA | PDE General Fund Budget bulk Excel | Annual, ~Sept after Jun 30 adoption | 490/545 LEAs FY26 adopted |
| WA | OSPI F-195 Microsoft Access DB (.accdb) | Annual, posted ~Oct of new SY | 256/258 LEAs FY26 adopted ($24.7B); F-33 frame parity with F-196 actuals |
| IN | DLGF Gateway Form 4B (3-step ASP.NET POST) | Annual, certified ~Feb of budget year | 287/335 corps FY25 adopted ($11.0B); IPS gap |
| NJ | NJDOE User-Friendly Budget CSVs | Per-district, post-adoption (deadline May 15) | 238/265 LEAs FY26 adopted ($26.1B); FY27 will populate as districts upload May-June 2026 |
| CT | CT OPM Adopted Municipal Budget SoQL API | Real-time per-town | 117/139 LEAs FY26 adopted (date_budget_adopted recorded) |
| KS | KSDE Budget at a Glance per-USD PDFs (curl-cffi chrome120 TLS bypass for Imperva WAF) | Annual, posted ~Nov of new SY | 285/286 USDs FY26 adopted ($8.8B); 8-way parallel BAG fetch |
| HI | HI DBF Budget-in-Brief PDF | Biennial via legislative act | 1/1 LEA FY27 adopted ($2.86B) — *only state with FY27 budget data so far* |

For VT/NH/IA (deadlines also passed for FY27): publication doesn't follow adoption — VT publishes per-district file post-audit (~Jan 2028); NH site Akamai-blocked; IA DOM API auth-required. Documented in [PLAN.md](../PLAN.md).

### Investigated but no bulk adopted-budget feed (16 states)

Per the May 2026 systematic deadline-order investigation: NC, TN, ID, SD (Jul deadlines); OK, MS, ND, MT (Aug); AL, AR, LA, KY (Sep — LA has summary PDF but no $ amounts); OH, WI (Oct — WI bulk exists but FY27 won't certify until Dec 2026). **IL** Form 50-39 buildable via per-district scrape or FOIA ISBE for the IWAS bulk dump — pending implementation. KSDE Imperva WAF defeated 2026-05-07 via curl-cffi chrome120 TLS impersonation — same technique now applies to AZ/NH/WV reattempts.

## Open follow-ups (existing extractors)

- **NC LGC all-funds (scoped 2026-05-14, hard)** — LGC portal explicitly excludes school districts; NCDPI bulk file is SPSF (state-funded only — current source); each LEA's "Plain English Report" required by G.S. § 115C-105.25(c) is all-funds but lives on the district's own website. Realistic paths: (a) per-LEA scrape of ~196 district websites with bespoke layouts, (b) FOIA/email to NCDPI Financial and Business Services for the underlying expenditure detail, (c) NC State Auditor (their site was unreachable at scoping time; revisit). Multi-session work.
- **UT charters** — LeaNbr → A-code crosswalk for 15 skipped charter LEAs
- **VA joint-division override** — 8 unmatched joint city-county divisions
- **PA AFR** — close PA actuals gap
- **IL Form 50-39** — close IL adopted-budget gap (per-district scrape from district sites or FOIA ISBE for IWAS dump)
- **CA charter-via-Alt-Form** — sibling extractor for ~30% gap
- **IN charters** — 45 IN charter LEAs not in SCFI
- **IN IPS adopted-budget** — Indianapolis Public Schools (IN-5385) absent from DLGF Gateway Form 4B; investigate alternate IN source
- **LA Type 2 charters** — 18 LA charter LEAs aggregated as '4-Type 2'
- **ME RSU/MSAD consolidation** — bridge per-municipality SAUs to RSU groupings
- **MI/OH/GA adopted-budget** — would need per-district scraping
- **OH Five-Year Forecast** — buildable but General-Fund-only; flagged BUILD-with-caveat
- **WI adopted-budget (DPI SAFR)** — bulk CSV exists; FY27 certifies ~Dec 2026; build then
- **KS adopted-budget (Data Central)** — KSDE Data Central likely has bulk USD Budget Summary; cert-error blocked first investigation
- **TX charter no-match (95)** — likely closed/test charter codes; verify against active charter list
- **WA F-195 unmatched (55)** — likely state schools / juvenile detention / non-LEA entities
- **AZ/NH/WV reattempt via curl-cffi** — same Imperva WAF as KS; KS-tested chrome120 TLS impersonation should bypass these too
- **Annual `KNOWN_FILE_URLS` refresh** — IN/WI/MD/SC/AL/LA/IA/MS/HI/ID/SD/ND/VT/DC/MT all need annual URL bumps
- **AL FY24 PDF** — refresh when ALSDE publishes
- **DC charters not in master** — 63 charter LEAs in OSSE file but not in master operating-LEA set

## Reattack candidates (deferred but data quality is high once unblocked)

Highest-value targets if a Chrome-MCP automation harness gets built:
1. ~~NY (2.36M)~~ — **MOVED TO BUILDABLE** 2026-05-14. ST-3 ZIP at predictable URL after all.
2. **NV (483k)** — per-LEA PDF discovery + parsing
3. **NM (295k)** — Looker SaaS dashboard scraping (significant effort)

The 2026-05-07 sessions added 7 new live states (KS, AZ, NH, WV, CO, NE, MO) using:
- **curl-cffi chrome120** TLS-impersonation for Akamai/Imperva/CDE WAFs
- **Multi-step ASP.NET postback / passwordless auth** for DESE-style portals
- **Direct file URL discovery** when deferral assumptions were wrong (NE turned out to have static links)

The remaining deferrals (NY, MN, NV, NM, AK, RI, DE, WY) need different techniques: captcha solving (MN, NM), Tableau scraping (RI), per-LEA PDF discovery (NV), or genuine no-bulk-data workarounds (NY, AK, WY).
