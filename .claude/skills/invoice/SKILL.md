---
name: invoice
description: Full invoicing pipeline - fetch hours from Clockify, preview, get approval, create proforma in Fakturoid, fire, and notify via Slack
---

# /invoice — Create and Issue Invoice

Full invoicing pipeline: fetch hours, preview, get approval, create proforma, fire, notify.

## Arguments

- `--start YYYY-MM-DD` (optional, defaults to first day of current month)
- `--end YYYY-MM-DD` (optional, defaults to last day of current month)
- `--rate N` (optional, uses DEFAULT_HOURLY_RATE from .env)
- `--dry-run` (optional, stop after preview — same as /preview)

## Steps

### 1. Fetch hours
Run: `uv run python -m invoicing fetch --start <start> --end <end>`
Parse the JSON output. If `total_hours` is 0, tell the user and stop.

### 2. Show preview and ask for approval
Present the same summary as /preview (hours, project breakdown, rate, subtotal, VAT, total).
**Ask the user explicitly**: "Create this invoice?" — do NOT proceed without a clear "yes".

### 3. Create proforma invoice
Run: `uv run python -m invoicing create --start <start> --end <end> --rate <rate>`
Parse the JSON output to get `invoice_id`, `invoice_number`, `total`, `fakturoid_url`.

### 4. Fire the invoice
Run: `uv run python -m invoicing fire --invoice-id <invoice_id>`
This finalizes the proforma into a real tax document.
If status is `"already_fired"`, Fakturoid auto-converted the proforma — this is normal, not an error.

### 5. Notify via Slack
Run: `uv run python -m invoicing notify --invoice-id <invoice_id>`
This sends a Slack message and uploads the invoice PDF to the configured channel.
Parse the JSON output to confirm `status: "notified"` and check `pdf_uploaded`.
Save `message_ts`, `channel_id`, and `file_id` from the output — needed if the user wants to delete the message later via `slack-delete --ts <message_ts> --channel-id <channel_id> --file-id <file_id>`.

## Error Recovery

- If step 3 succeeds but step 4 fails (and status is NOT `"already_fired"`): tell the user the proforma exists and offer to retry firing or delete it.
- If any step fails: show the error clearly. If a proforma was created, remind the user it can be cleaned up with `uv run python -m invoicing delete --invoice-id <id>`.
- Never leave a proforma behind without telling the user.
