# psychic-garbanzo — Invoicing Automation

Freelance invoicing pipeline: **Clockify** (time tracking) → **Fakturoid** (Czech invoicing) → **Slack** (notification).

## Tech Stack

- Python 3.12+, managed with `uv`
- httpx (async HTTP), pydantic + pydantic-settings
- No ORM, no database — stateless CLI that talks to external APIs

## Setup

```bash
uv sync                  # install deps
cp .env.example .env     # fill in API keys
uv sync --group dev      # install pytest
```

## CLI Usage

Full pipeline (terminal with interactive approval):
```bash
uv run python -m invoicing run --start 2026-03-01 --end 2026-03-31 --rate 100
```

Step-by-step (for Claude Code orchestration):
```bash
uv run python -m invoicing fetch   --start 2026-03-01 --end 2026-03-31
uv run python -m invoicing create  --start 2026-03-01 --end 2026-03-31 --rate 100
uv run python -m invoicing fire    --invoice-id 123
uv run python -m invoicing delete  --invoice-id 123
uv run python -m invoicing notify  --invoice-id 123
uv run python -m invoicing notify  --invoice-number FV-123 --hours 10 --amount "1000 CZK" --client "Acme" --period "2026-03-01 - 2026-03-31"
uv run python -m invoicing slack-delete --ts 1234567890.123456 --channel-id C0ABC --file-id F0XYZ
```

All subcommands output JSON to stdout for easy parsing.

## Project Structure

```
invoicing/
  __main__.py   — CLI entry point, argument parser, pipeline orchestration
  config.py     — InvoicingSettings (pydantic-settings, reads .env)
  clockify.py   — Clockify API client (fetch time entries)
  fakturoid.py  — Fakturoid API client (OAuth, create/fire/delete invoices)
  slack.py      — Slack Bot Token notifier (chat.postMessage + PDF upload)
  workflows.py  — Shared helpers (invoice draft, URL building, formatting)
```

## Invoicing Workflow (Claude Code Orchestration)

When orchestrating step-by-step, follow this sequence:

1. **Fetch** hours from Clockify → get `total_hours`, entries breakdown
2. **Show preview** to user (hours, rate, total) and ask for approval
3. **Create** proforma invoice in Fakturoid → get `invoice_id`
4. **Fire** the proforma to finalize it as a real invoice
5. **Notify** via Slack (`uv run python -m invoicing notify --invoice-id <id>`)

If user rejects at step 2, stop. If something goes wrong after step 3, use `delete` to clean up the proforma.

## Conventions

- Async everywhere (httpx.AsyncClient)
- Config via environment variables / `.env` (never hardcode secrets)
- JSON output from CLI subcommands for machine readability
- No classes where functions suffice — keep it flat and functional
- Currency is CZK, VAT default 0% (configurable via DEFAULT_VAT_RATE)
- `uv run` to execute anything (not raw `python`)
