---
name: yolo
description: Send an invoice for the last complete month to Slack without preview or approval
---

# /yolo — Invoice Last Month, No Questions Asked

Fire-and-forget invoicing: fetch hours for the last complete month, create proforma, fire it, notify via Slack. No preview, no approval prompt.

## Arguments

- `--rate N` (optional, uses DEFAULT_HOURLY_RATE from .env)

## Date Calculation

Compute the **last complete calendar month** relative to today's date:
- **Start**: first day of previous month (e.g. if today is 2026-04-15, start = 2026-03-01)
- **End**: last day of previous month (e.g. 2026-03-31)

## Steps

Run all steps sequentially. Do NOT ask for user confirmation at any point.

### 1. Fetch hours
Run: `uv run python -m invoicing fetch --start <start> --end <end>`
Parse the JSON output. If `total_hours` is 0, tell the user "No hours tracked for <period>" and stop.

### 2. Create proforma invoice
Run: `uv run python -m invoicing create --start <start> --end <end> --rate <rate>`
Parse the JSON output to get `invoice_id`, `invoice_number`, `total`, `fakturoid_url`.

### 3. Fire the invoice
Run: `uv run python -m invoicing fire --invoice-id <invoice_id>`
This finalizes the proforma into a real tax document.
If status is `"already_fired"`, Fakturoid auto-converted the proforma — this is normal, not an error.

### 4. Notify via Slack
Run: `uv run python -m invoicing notify --invoice-id <invoice_id>`
This sends a Slack message and uploads the invoice PDF to the configured channel.
Parse the JSON output to confirm `status: "notified"` and check `pdf_uploaded`.
Save `message_ts`, `channel_id`, and `file_id` from the output — needed if the user wants to delete the message later via `slack-delete --ts <message_ts> --channel-id <channel_id> --file-id <file_id>`.

### 5. Report
Show a brief summary: invoice number, total amount, Fakturoid URL, and Slack notification status.

## Error Recovery

- If step 2 succeeds but step 3 fails (and status is NOT `"already_fired"`): tell the user the proforma exists and offer to retry firing or delete it.
- If any step fails: show the error clearly. If a proforma was created, remind the user it can be cleaned up with `uv run python -m invoicing delete --invoice-id <id>`.
- Never leave a proforma behind without telling the user.
