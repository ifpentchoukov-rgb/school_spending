"""Detect extractors with N consecutive failed runs.

Reads `extraction_runs`, partitions by extractor_name, looks at the most
recent N runs (default 2) per extractor; flags any extractor where ALL of
those runs are status='failed'.

Exits non-zero if any extractor is flagged. Prints a markdown-friendly
report on stdout (the workflow captures it for the GitHub Issue body).

Usage in CI:
    python -m runner.check_failures --consecutive 2 > /tmp/failures.md
    if [ $? -ne 0 ]; then
        gh issue create --title "..." --body-file /tmp/failures.md
    fi
"""

from __future__ import annotations

import argparse
import sys

from extractors._client import get_client


def check(consecutive: int = 2) -> tuple[bool, str]:
    """Return (any_flagged, markdown_report)."""
    client = get_client()

    rows = (
        client.table("extraction_runs")
        .select("extractor_name")
        .execute()
    ).data or []
    extractor_names = sorted({r["extractor_name"] for r in rows})

    flagged: list[tuple[str, list[dict]]] = []
    for name in extractor_names:
        recent = (
            client.table("extraction_runs")
            .select("status, started_at, error_summary")
            .eq("extractor_name", name)
            .order("started_at", desc=True)
            .limit(consecutive)
            .execute()
        ).data or []
        if len(recent) >= consecutive and all(r["status"] == "failed" for r in recent):
            flagged.append((name, recent))

    lines: list[str] = []
    if not flagged:
        lines.append(f"OK: no extractor has {consecutive} consecutive failed runs.")
        lines.append(f"Checked {len(extractor_names)} extractor(s): "
                     f"{', '.join(extractor_names) or '<none>'}")
        return False, "\n".join(lines)

    lines.append(f"## {len(flagged)} extractor(s) with {consecutive}+ consecutive failures")
    lines.append("")
    for name, runs in flagged:
        lines.append(f"### `{name}`")
        for r in runs:
            err = (r.get("error_summary") or "").strip()[:600]
            lines.append(f"- `{r['started_at']}` — {r['status']}")
            if err:
                lines.append("  ```")
                for line in err.splitlines()[-15:]:
                    lines.append(f"  {line}")
                lines.append("  ```")
        lines.append("")
    lines.append("---")
    lines.append("Auto-opened by `runner/check_failures.py`. Investigate and "
                 "either fix the underlying issue or close this issue once "
                 "the extractor recovers.")
    return True, "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--consecutive", type=int, default=2,
                   help="Number of consecutive failed runs that triggers an alert")
    args = p.parse_args()

    flagged, report = check(consecutive=args.consecutive)
    print(report)
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
