# Progress tracker

`TreasuryPilot-Tracker.xlsx` is a **report generated from GitHub**. The GitHub Project "TreasuryPilot · Delivery" is the source of truth (decision Q19).

Refresh:

```bash
uv run --with openpyxl python planning/tracker/build_tracker.py
```

| Sheet | Content |
|---|---|
| Issues | One row per ticket: ID, GH #, title, module, epic, priority, phase, size, est. days, cut, area, status, assignees, blocked-by, open blockers, link |
| Module Progress | Per module: tickets, done, in progress, review, not started, % done by count and by effort, Cut A progress |
| Status Summary | Ticket counts per status (all, Cut A, Cut B, M1, Later) |
| Dependencies | One row per blocked-by link, with the status of both sides and whether it is blocking now |
| How to use | Notes |

All totals are Excel formulas, so they recalculate if you play with statuses locally. Real changes belong in the GitHub Project.
