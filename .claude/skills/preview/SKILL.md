---
name: preview
description: Fetch hours from Clockify and show an invoice cost preview (read-only, no invoices created)
---

# /preview — Invoice Preview

Fetch hours from Clockify and show a cost preview. No invoices are created — this is read-only.

## Arguments

- `--start YYYY-MM-DD` (optional, defaults to first day of current month)
- `--end YYYY-MM-DD` (optional, defaults to today)
- `--rate N` (optional, uses DEFAULT_HOURLY_RATE from .env)

## Steps

1. Determine the date range. If no arguments given, use current month (first day → today).
2. Run: `uv run python -m invoicing fetch --start <start> --end <end>`
3. Parse the JSON output.
4. Present a summary to the user:
   - Total hours and entry count
   - Breakdown by project (from `by_project`)
   - If `--rate` or DEFAULT_HOURLY_RATE is known, show:
     - Subtotal (hours × rate)
     - VAT line only if DEFAULT_VAT_RATE > 0
     - Total in CZK
5. Do NOT create, fire, or modify anything. This is preview only.

Note: the actual invoice (when run via `/invoice` or `/yolo`) will be issued on the last day of the period's calendar month, not today.

## Output Format

Present as a clean table/summary in the terminal. Example:

```
Period: <start> → <end>
Hours:  <total_hours> (<entry_count> entries)

By project:
  <project_1>    <hours_1> hrs
  <project_2>    <hours_2> hrs

Rate:     <rate> CZK/hr
Subtotal: <subtotal> CZK
VAT:      <vat> CZK        ← only if VAT rate > 0
Total:    <total> CZK
```
