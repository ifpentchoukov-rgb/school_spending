#!/usr/bin/env python3
"""Probe for newly-published state DOE financial data files.

Most state DOEs publish per-LEA financial data on a 9–18 month lag.
We have known URL patterns for each state's annual file. This script
walks a registry of (state, fiscal_year, status, candidate_urls) and
checks whether any of the candidates returns HTTP 200 with the right
content-type — surfacing newly-available files between releases.

When a new file lands, the operator should add its URL to the
extractor's `KNOWN_FILE_URLS` dict and re-run the extractor. With
`--apply`, the script does both automatically (in-place edit + run).

Intended cadence: monthly. The expected publication windows are
documented in `PLAN.md` per-state; this script just speeds up the
"is it there yet?" check across all states at once.

Usage:
    python scripts/probe_new_files.py
    python scripts/probe_new_files.py --json > probe-2026-05.json
    python scripts/probe_new_files.py --apply  # edits + runs extractor
    python scripts/probe_new_files.py --filter-state MD  # one state only

Cron suggestion (1st of month, 7am local):
    0 7 1 * * cd /path/to/school_spending && \\
        .venv/bin/python scripts/probe_new_files.py --apply \\
        > /tmp/probe-$(date +\\%Y\\%m).log 2>&1

Output (default = human-readable):
    [FY25 actuals]
      MD  HIT  https://...  (1.2MB)
      IL  miss
      ...
    [FY27 adopted]
      NJ  HIT  https://...  (4.5MB)
      ...
    Summary: 2 hits, 14 misses. Use --apply to ingest hits.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import importlib
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from curl_cffi import requests as curl_req


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ProbeTarget:
    """A (state, fy, status) we want to ingest, with one or more URL
    candidates to try. The first 200-OK candidate wins."""
    state: str
    fiscal_year: int
    status: str  # "actual" | "adopted"
    module: str  # extractors.<name>
    url_candidates: list[str] = field(default_factory=list)
    note: str = ""
    # Optional: a callable that returns extra URL candidates dynamically
    # (e.g. for sources that timestamp filenames or list dynamically).
    dynamic_resolver: object = None


@dataclass
class ProbeResult:
    target: ProbeTarget
    hit_url: str | None
    size: int
    content_type: str
    status_code: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Probe registry
# ---------------------------------------------------------------------------
# For each "missing FY", list the URL patterns most likely to materialize.
# Use the same predicates the per-state extractor uses where possible —
# the source URL is the source of truth for the file we want to ingest.

def _wi_compcost_urls(fiscal_year: int) -> list[str]:
    """WI DPI Comparative Cost Per Member files include a date timestamp
    in the filename (e.g. district_2324_compcost_20260317.xlsx). The base
    pattern is district_{YY1}{YY2}_compcost_*.xlsx. We can't predict the
    timestamp, but we can scrape the SFS index page for the link."""
    yy1 = (fiscal_year - 1) % 100
    yy2 = fiscal_year % 100
    return [
        f"https://dpi.wi.gov/sites/default/files/imce/sfs/xls/"
        f"district_{yy1:02d}{yy2:02d}_compcost.xlsx",  # un-timestamped
    ]


def _build_targets() -> list[ProbeTarget]:
    """Build the registry of probe targets.

    Each entry covers one (state, fy, status) we don't yet have. Add
    new states here as they're built; remove entries as they're ingested.
    """
    fy25 = 2025
    fy27 = 2027
    targets: list[ProbeTarget] = [
        # --- FY25 ACTUALS missing ---
        ProbeTarget(
            state="MD", fiscal_year=fy25, status="actual",
            module="extractors.md",
            url_candidates=[
                "https://marylandpublicschools.org/about/Documents/DBS/SFD/2024-2025/Selected-Financial-Data-2024-2025-Part2-A.pdf",
                "https://www.marylandpublicschools.org/about/Documents/DBS/SFD/2024-2025/Selected-Financial-Data-2024-2025-Part2-A.pdf",
                "https://marylandpublicschools.org/about/Pages/DBS/SFD/2024-2025/index.aspx",
            ],
            note="MSDE typically publishes June; FY24 lives at /2023-2024/...",
        ),
        ProbeTarget(
            state="IL", fiscal_year=fy25, status="actual",
            module="extractors.il",
            url_candidates=[
                "https://www.isbe.net/Documents/FY25-OEPP-PCTC.xlsx",
                "https://www.isbe.net/Documents/FY2025-OEPP-PCTC.xlsx",
                "https://www.isbe.net/_layouts/Download.aspx?SourceUrl=/Documents/FY25-OEPP-PCTC.xlsx",
            ],
            note="ISBE OEPP-PCTC; FY24 already in KNOWN_FILE_URLS",
        ),
        ProbeTarget(
            state="MA", fiscal_year=fy25, status="actual",
            module="extractors.ma",
            url_candidates=[
                "https://profiles.doe.mass.edu/statereport/ppx.aspx?fycode=2025",
                # If the dropdown returns a CSV link directly:
                "https://profiles.doe.mass.edu/statereport/ppx_2025.aspx",
            ],
            note="DESE PPX dropdown; check for FY25 option in the page HTML",
        ),
        ProbeTarget(
            state="KY", fiscal_year=fy25, status="actual",
            module="extractors.ky",
            url_candidates=[
                "https://www.education.ky.gov/districts/FinRept/Documents/Revenues%20and%20Expenditures%202024-2025.xlsx",
                "https://www.education.ky.gov/districts/FinRept/Documents/Revenues+and+Expenditures+2024-2025.xlsx",
                "https://www.education.ky.gov/districts/FinRept/Documents/Revenues and Expenditures 2024-2025.xlsx",
            ],
            note="KDE AFR R&E; FY24 lives at .../Revenues and Expenditures 2023-2024.xlsx",
        ),
        ProbeTarget(
            state="SC", fiscal_year=fy25, status="actual",
            module="extractors.sc",
            url_candidates=[
                "https://ed.sc.gov/finance/financial-data/in-ite/fiscal-year-2025-abbeville-greenwood-52/",
            ],
            note="SCDE In$ite per-district; FY24 path uses fiscal-year-2024-... segment",
        ),
        ProbeTarget(
            state="NJ", fiscal_year=fy25, status="actual",
            module="extractors.nj",
            url_candidates=[
                "https://www.nj.gov/education/guide/docs/2026/Detail_FY25.xlsx",
                "https://www.nj.gov/education/guide/docs/2027/Detail_FY25.xlsx",
            ],
            note="NJ TGES; FY24 at /2025/Detail_FY24.xlsx",
        ),
        ProbeTarget(
            state="WI", fiscal_year=fy25, status="actual",
            module="extractors.wi",
            url_candidates=_wi_compcost_urls(fy25),
            note="WI DPI Comparative Cost; filename has a date timestamp",
        ),
        ProbeTarget(
            state="CO", fiscal_year=fy25, status="actual",
            module="extractors.co",
            url_candidates=[
                "https://www.cde.state.co.us/cdefinance/ft_fy2025_distdatafile",
            ],
            note="CDE FT; predictable URL pattern",
        ),
        ProbeTarget(
            state="IN", fiscal_year=fy25, status="actual",
            module="extractors.in_",
            url_candidates=[
                "https://hub.mph.in.gov/dataset/duab-school-corporation-financial-information-scfi/resource/scfi-data-2026-release-adm-fund-balances-deficit-surplus-1.xlsx",
                # 2025-release CY 2014-2024 may already cover FY25 partially:
                "https://hub.mph.in.gov/dataset/duab-school-corporation-financial-information-scfi/resource/scfi-data-2025-release-adm-fund-balances-deficit-surplus-1.xlsx",
            ],
            note="IN SCFI; CY-based — 2025-release covers CY2014-2024",
        ),
        ProbeTarget(
            state="AL", fiscal_year=2024, status="actual",
            module="extractors.al",
            url_candidates=[
                "https://www.alabamaachieves.org/wp-content/uploads/2025/01/PPE-Detail-FY24.pdf",
                "https://www.alabamaachieves.org/wp-content/uploads/2025/12/PPE-Detail-FY24.pdf",
                "https://www.alabamaachieves.org/wp-content/uploads/2026/01/PPE-Detail-FY24.pdf",
            ],
            note="AL is 2 FYs behind (latest FY23); FY24 expected anytime",
        ),

        # --- FY27 ADOPTED budgets opening (May-Nov 2026 deadlines) ---
        ProbeTarget(
            state="NJ", fiscal_year=fy27, status="adopted",
            module="extractors.nj_budget",
            url_candidates=[
                "https://www.nj.gov/education/budget/ufb/2627/download/approp27.csv",
            ],
            note="NJ UFB; districts adopt by May 15. FY26 at /2526/approp26.csv",
        ),
        ProbeTarget(
            state="PA", fiscal_year=fy27, status="adopted",
            module="extractors.pa",
            url_candidates=[
                "https://www.education.pa.gov/Documents/Teachers-Administrators/School%20Finances/Education%20Budget/2026-27gfbdata.xlsx",
                "https://www.education.pa.gov/Documents/Teachers-Administrators/School%20Finances/Education%20Budget/2026-27GFBData.xlsx",
            ],
            note="PDE GFB; districts adopt by Jun 30. FY26 at .../2025-26gfbdata.xlsx",
        ),
        ProbeTarget(
            state="WV", fiscal_year=fy27, status="adopted",
            module="extractors.wv",
            url_candidates=[
                # FY27 final replaces the preliminary already in KNOWN_FILE_URLS
                # We'll discover the final URL by scanning wvde.us/finance pages
                "https://wvde.us/about-us/finance/school-finance/school-finance-data/2026-2027",
            ],
            note="WVDE PSSP FY27 final replaces the prelim already saved",
        ),
        ProbeTarget(
            state="WA", fiscal_year=fy27, status="adopted",
            module="extractors.wa_budget",
            url_candidates=[
                "https://ospi.k12.wa.us/sites/default/files/safs/AF1952627.accdb",
            ],
            note="OSPI F-195; districts adopt by Aug 31. FY26 at .../AF1952526.accdb",
        ),
        ProbeTarget(
            state="TX", fiscal_year=fy27, status="adopted",
            module="extractors.tx_budget",
            url_candidates=[
                "https://tea.texas.gov/reports-and-data/financial-reports/school-finance-reports-and-data/budget2027.zip",
            ],
            note="TEA PEIMS; FY26 at .../budget2026.zip; expected ~Feb 2027",
        ),
        ProbeTarget(
            state="KS", fiscal_year=fy27, status="adopted",
            module="extractors.ks_budget",
            url_candidates=[
                # KSDE BAGs are 285 individual PDFs at predictable URLs,
                # gated by the per-USD orgsByYear endpoint. Probe just
                # the orgs API to see if FY27 is published.
                "https://datacentral.ksde.gov/scripts/services/dataService.svc/orgsByYear?progYear=2027",
            ],
            note="KSDE BAGs; FY26 published Nov 2025; FY27 expected Nov 2026",
        ),
        ProbeTarget(
            state="IN", fiscal_year=fy27, status="adopted",
            module="extractors.in_budget",
            url_candidates=[
                # DLGF Form 4B is fetched via 3-step ASP.NET POST; we
                # check the public download.aspx for the 2026 year option
                # in the year dropdown.
                "https://gateway.ifionline.org/public/download.aspx",
            ],
            note="DLGF Gateway Form 4B; FY27 = DLGF year=2026; expected ~Feb 2027",
        ),
        ProbeTarget(
            state="HI", fiscal_year=fy27, status="adopted",
            module="extractors.hi_budget",
            url_candidates=[
                # HI is biennial — already FY27 ingested via 2025-27 act
                # Nothing to probe; included for completeness only.
            ],
            note="HI biennial — already at FY27 ($2.86B from 2025-27 act)",
        ),
    ]
    return targets


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

def _probe_url(url: str, *, timeout: int = 30) -> tuple[int, int, str, str | None]:
    """Return (status_code, content_length, content_type, error_or_None)."""
    try:
        r = curl_req.get(
            url,
            impersonate="chrome120",
            verify=False,
            timeout=timeout,
            headers={"Referer": url.rsplit("/", 2)[0] + "/"},
        )
        return r.status_code, len(r.content), r.headers.get("content-type", ""), None
    except Exception as e:
        return 0, 0, "", f"{type(e).__name__}: {e}"


def _content_type_ok(ct: str, status: str) -> bool:
    """Quick sanity: a 200 with a tiny HTML page is usually a 'no'.
    A real data file is application/pdf, .xlsx, .csv, .zip, application/octet-stream, etc.
    For HTML probes (e.g. SCDE landing page) we accept text/html if size > 5KB.
    """
    ct_low = ct.lower()
    if any(t in ct_low for t in (
        "application/pdf", "application/vnd.ms-excel",
        "application/vnd.openxmlformats", "text/csv",
        "application/zip", "application/octet-stream",
        "application/x-msaccess",
    )):
        return True
    return False


def probe_target(target: ProbeTarget) -> ProbeResult:
    """Try each URL candidate; return first hit (200 + reasonable
    content-type) or last miss."""
    last: ProbeResult | None = None
    for url in target.url_candidates:
        status_code, size, ct, err = _probe_url(url)
        last = ProbeResult(
            target=target, hit_url=url, size=size,
            content_type=ct, status_code=status_code, error=err,
        )
        if status_code == 200 and _content_type_ok(ct, target.status):
            # Strong hit
            return last
        # else: try next candidate
    # No strong hit; return the last attempt with hit_url=None
    if last is None:
        return ProbeResult(
            target=target, hit_url=None, size=0, content_type="",
            status_code=0, error="no candidates",
        )
    last.hit_url = None
    return last


# ---------------------------------------------------------------------------
# Apply (auto-update KNOWN_FILE_URLS + run extractor)
# ---------------------------------------------------------------------------

_KNOWN_FILE_URLS_RE = re.compile(
    r"(KNOWN_FILE_URLS\s*:\s*dict\[int,\s*str\]\s*=\s*\{)([^}]*)(\})",
    re.S,
)


def _module_to_path(module_name: str) -> Path:
    """extractors.foo -> /repo/extractors/foo.py"""
    rel = module_name.replace(".", "/") + ".py"
    return REPO_ROOT / rel


def patch_known_file_urls(module_name: str, fiscal_year: int, url: str) -> bool:
    """Add `fiscal_year: "url"` to the module's KNOWN_FILE_URLS dict.
    Returns True if patched, False if already present or not found."""
    path = _module_to_path(module_name)
    if not path.exists():
        return False
    text = path.read_text()
    m = _KNOWN_FILE_URLS_RE.search(text)
    if not m:
        return False
    body = m.group(2)
    if f"{fiscal_year}:" in body:
        return False  # already there
    # Indent — pick from the existing body if present, else default 4-space.
    indent_match = re.search(r"\n( +)\d+:", body)
    indent = indent_match.group(1) if indent_match else "    "
    # The body normally ends with `,\n` before the closing `}`. Insert
    # `{indent}{fy}: "url",\n` right before that final `}` line, replacing
    # any trailing whitespace inside the body.
    body_stripped = body.rstrip()
    new_body = f'{body_stripped}\n{indent}{fiscal_year}: "{url}",\n'
    new_text = text[: m.start(2)] + new_body + text[m.end(2):]
    path.write_text(new_text)
    return True


def run_extractor(module_name: str, fiscal_year: int) -> tuple[bool, str]:
    """Run `python -m {module} --fiscal-year {fy}` from the repo root.
    Returns (success, captured_output)."""
    py = REPO_ROOT / ".venv" / "bin" / "python"
    if not py.exists():
        py = "python"
    cmd = [str(py), "-m", module_name, "--fiscal-year", str(fiscal_year),
           "--triggered-by", "cron"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900, cwd=REPO_ROOT,
        )
        ok = proc.returncode == 0
        return ok, proc.stdout + proc.stderr
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_result(r: ProbeResult) -> str:
    t = r.target
    if r.hit_url:
        size_mb = r.size / 1e6
        return (
            f"  {t.state:3} {'HIT':4} fy{t.fiscal_year} {t.status:7} "
            f"{r.hit_url[:90]}  ({size_mb:.2f} MB, {r.content_type})"
        )
    # Distinguish miss types:
    if r.error:
        detail = f"err: {r.error[:60]}"
    elif r.status_code == 200:
        # Got a 200 but content-type wasn't a recognized data file —
        # most likely a SharePoint/CMS custom 404 page or landing page.
        detail = f"200/non-data ({r.content_type[:40]})"
    elif r.status_code:
        detail = f"HTTP {r.status_code}"
    else:
        detail = "no probe"
    return (
        f"  {t.state:3} {'miss':4} fy{t.fiscal_year} {t.status:7}  "
        f"{detail} — {t.note}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="For each HIT: edit module's KNOWN_FILE_URLS and run extractor")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of human-readable output")
    p.add_argument("--filter-state", default=None,
                   help="Only probe a single state (e.g. MD)")
    args = p.parse_args()

    targets = _build_targets()
    if args.filter_state:
        targets = [t for t in targets if t.state == args.filter_state.upper()]

    results: list[ProbeResult] = []
    if not args.json:
        print(f"Probing {len(targets)} targets at {datetime.datetime.now().isoformat(timespec='seconds')}\n")

    # Group output by status (actuals first, then adopted)
    grouped: dict[tuple[int, str], list[ProbeTarget]] = {}
    for t in targets:
        grouped.setdefault((t.fiscal_year, t.status), []).append(t)

    for (fy, status), group in sorted(grouped.items()):
        if not args.json:
            print(f"[FY{fy} {status}]")
        for t in group:
            r = probe_target(t)
            results.append(r)
            if not args.json:
                print(_format_result(r))
        if not args.json:
            print()

    hits = [r for r in results if r.hit_url]
    misses = [r for r in results if not r.hit_url]

    if args.json:
        out = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "n_hits": len(hits),
            "n_misses": len(misses),
            "results": [
                {
                    "state": r.target.state,
                    "fiscal_year": r.target.fiscal_year,
                    "status": r.target.status,
                    "module": r.target.module,
                    "hit_url": r.hit_url,
                    "size": r.size,
                    "content_type": r.content_type,
                    "status_code": r.status_code,
                    "error": r.error,
                    "note": r.target.note,
                }
                for r in results
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(
            f"Summary: {len(hits)} hits, {len(misses)} misses.\n"
            + (f"Use --apply to ingest the {len(hits)} hits."
               if hits and not args.apply else "")
        )

    if args.apply and hits:
        if not args.json:
            print("\n=== Applying hits ===\n")
        for r in hits:
            t = r.target
            patched = patch_known_file_urls(t.module, t.fiscal_year, r.hit_url)
            if patched:
                if not args.json:
                    print(
                        f"  {t.state} fy{t.fiscal_year} "
                        f"{t.status}: patched {t.module}; running extractor..."
                    )
                ok, out = run_extractor(t.module, t.fiscal_year)
                if not args.json:
                    tail = "\n".join(out.splitlines()[-6:])
                    print(f"    {'✓' if ok else '✗'} {tail}")
            else:
                if not args.json:
                    print(
                        f"  {t.state} fy{t.fiscal_year}: already in "
                        f"KNOWN_FILE_URLS; skipping patch (run extractor manually)"
                    )

    # Exit non-zero only on probe errors (not on misses — misses are expected).
    return 0


if __name__ == "__main__":
    sys.exit(main())
