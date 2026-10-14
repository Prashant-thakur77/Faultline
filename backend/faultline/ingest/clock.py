"""The single time anchor for every generated history (never the wall clock).

All ingest producers derive their timestamps from `ANCHOR_MS` so builds are byte-identical across
runs and machines. Times are epoch milliseconds (UTC).
"""

from __future__ import annotations

ANCHOR_MS = 1792022400000  # 2026-10-15T00:00:00Z: hackathon kickoff; "now" for the seeded tenants

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS
WEEK_MS = 7 * DAY_MS

HISTORY_DAYS = 120
HISTORY_START_MS = ANCHOR_MS - HISTORY_DAYS * DAY_MS  # first commit/deploy/incident may happen here
HISTORY_END_MS = ANCHOR_MS - DAY_MS  # nothing in the generated history happens after this

ROTA_START_MS = ANCHOR_MS - HISTORY_DAYS * DAY_MS  # on-call rota covers the whole history …
ROTA_END_MS = ANCHOR_MS + 30 * DAY_MS  # … and the next 30 days (demo and eval runs)

ORG_EPOCH_MS = ANCHOR_MS - 400 * DAY_MS  # when the current org (teams, memberships) was formed


def day_start(day_index: int) -> int:
    """Epoch ms of 00:00Z on history day `day_index` (0 = ANCHOR − 120 days)."""
    return HISTORY_START_MS + day_index * DAY_MS
