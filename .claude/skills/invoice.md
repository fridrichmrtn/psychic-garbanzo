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

### 5. Notify via Slack
Use the MCP `slack_send_message` tool to post to the invoicing channel. Preferred over webhook.

Use `slack_search_channels` to find the right channel if not known.

Message format:
```
:white_check_mark: Invoice #<number> issued
Client: <subject_name>
Period: <start> — <end>
Hours: <total_hours>
Total: <total> CZK
<fakturoid_url>
```

If MCP Slack is unavailable, fall back to:
`uv run python -m invoicing notify --invoice-number <num> --hours <hrs> --amount "<total> CZK" --client "<name>" --period "<start> - <end>"`

## Error Recovery

- If step 3 succeeds but step 4 fails: tell the user the proforma exists and offer to retry firing or delete it.
- If any step fails: show the error clearly. If a proforma was created, remind the user it can be cleaned up with `uv run python -m invoicing delete --invoice-id <id>`.
- Never leave a proforma behind without telling the user.
