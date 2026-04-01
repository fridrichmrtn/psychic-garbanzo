---
name: notify
description: Send an invoice notification to Slack after manual invoicing or when the /invoice notification step was skipped
---

# /notify — Send Invoice Notification to Slack

Post an invoice notification to Slack. Useful after manual invoicing or when the /invoice notification step was skipped.

## Arguments

- `--invoice-id` (preferred) — Fakturoid invoice ID; details are fetched automatically and PDF is uploaded
- `--invoice-number` (manual fallback) — e.g. "FV-2026-001"
- `--hours` (manual fallback) — total billable hours
- `--amount` (manual fallback) — e.g. "<total> CZK"
- `--client` (manual fallback) — client name
- `--period` (manual fallback) — e.g. "2026-03-01 - 2026-03-31"

If `--invoice-id` is provided, the other args are not needed (they are fetched from Fakturoid).
If `--invoice-id` is not provided, all manual args are required (text-only notification, no PDF). Ask the user for any missing ones.

## Steps

1. With `--invoice-id` (preferred):
   `uv run python -m invoicing notify --invoice-id <id>`
   This auto-fetches invoice details, sends the Slack message, and uploads the PDF.

2. With manual args (text-only, no PDF):
   `uv run python -m invoicing notify --invoice-number <num> --hours <hrs> --amount "<amount>" --client "<client>" --period "<period>"`

3. Parse the JSON output to confirm `status: "notified"` and report `pdf_uploaded` status to the user.

## Notes

- Requires `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` in `.env`.
- When `--invoice-id` is used, the invoice PDF is automatically downloaded from Fakturoid and uploaded to Slack. If PDF download/upload fails, the text notification is still sent.
