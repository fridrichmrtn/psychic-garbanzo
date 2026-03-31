# /notify — Send Invoice Notification to Slack

Post an invoice notification to Slack. Useful after manual invoicing or when the /invoice notification step was skipped.

## Arguments

- `--invoice-number` (required) — e.g. "FV-2026-042"
- `--hours` (required) — total billable hours
- `--amount` (required) — e.g. "77,138 CZK"
- `--client` (required) — client name
- `--period` (required) — e.g. "2026-03-01 - 2026-03-31"

If arguments are missing, ask the user for them.

## Steps

1. Use MCP `slack_search_channels` to find the invoicing/billing channel (if not already known).
2. Use MCP `slack_send_message` to post:

```
:white_check_mark: Invoice #<invoice-number> issued
Client: <client>
Period: <period>
Hours: <hours>
Total: <amount>
```

3. If MCP Slack is unavailable, fall back to:
   `uv run python -m invoicing notify --invoice-number <num> --hours <hrs> --amount "<amount>" --client "<client>" --period "<period>"`

## Notes

- Always prefer MCP `slack_send_message` over the webhook fallback.
- Confirm the channel with the user before posting if unsure.
