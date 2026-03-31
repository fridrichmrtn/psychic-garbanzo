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
     - VAT 21%
     - Total in CZK
5. Do NOT create, fire, or modify anything. This is preview only.

## Output Format

Present as a clean table/summary in the terminal. Example:

```
Period: 2026-03-01 → 2026-03-31
Hours:  42.50 (28 entries)

By project:
  Acme Platform    32.25 hrs
  Internal Ops     10.25 hrs

Rate:     1,500 CZK/hr
Subtotal: 63,750 CZK
VAT 21%:  13,388 CZK
Total:    77,138 CZK
```
