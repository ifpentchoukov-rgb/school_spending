"""Shared exceptions for extractor flow control.

`SourceNotYetPublished` is raised by an extractor when the upstream
source URL is the right URL but the file simply hasn't been published
yet (e.g. NJ FY27 UFB CSVs land between May 15 and June; PA FY27 GFB
certifies in September). The Run context manager records these as
status='partial' rather than 'failed', so the daily-failure alarm
(`runner.check_failures`) doesn't keep paging on a known-pre-publication
state.

Subclasses RuntimeError so any existing `except RuntimeError` block
still works; new code that wants the special handling should catch
this type explicitly.
"""

from __future__ import annotations


class SourceNotYetPublished(RuntimeError):
    """The source file's URL is correct but the file is not yet posted.

    Raise this when:
      - A `KNOWN_FILE_URLS[fy]` entry is missing because we haven't seen
        the FY published yet;
      - A predicted URL pattern returns 404 and the publication window
        for that FY hasn't yet closed;
      - A portal lists the year but the file payload is still being
        prepared (e.g. zero-byte placeholder).

    Do NOT raise this for genuine breakage (URL pattern changed, source
    portal moved, parser failed) — those should remain RuntimeError /
    other exceptions so they surface as `failed` and trip the alarm.
    """
