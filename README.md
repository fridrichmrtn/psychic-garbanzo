# psychic-garbanzo — Invoicing Automation

Freelance invoicing pipeline: **Clockify** (time tracking) → **Fakturoid** (Czech invoicing) → **Slack** (notification).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Accounts on [Clockify](https://clockify.me), [Fakturoid](https://www.fakturoid.cz), and [Slack](https://slack.com)

## Service Setup

### Clockify

Generate an API key for fetching time entries.

1. Log in to [Clockify](https://clockify.me)
2. Go to **Profile Settings** → **API** → generate an API key
3. Copy the key — this becomes `CLOCKIFY_API_KEY`

### Fakturoid

Create an OAuth app so the tool can issue invoices on your behalf.

1. Log in to [Fakturoid](https://app.fakturoid.cz)
2. Go to **Settings** → **Developer** → **OAuth Apps** → create a new app
3. Copy the **Client ID** and **Client Secret** — these become `FAKTUROID_CLIENT_ID` and `FAKTUROID_CLIENT_SECRET`
4. Note your account slug (the subdomain in your Fakturoid URL, e.g. `martinfridrich`) — this becomes `FAKTUROID_SLUG`
5. Set `FAKTUROID_SUBJECT_NAME` to the client company name that invoices are issued to

> **Note:** Ensure your default payment terms (splatnost) are configured in **Nastavení** — either under **Doklady** (invoice defaults) or **Dodavatel** (supplier details). The tool does not set due dates explicitly, so invoices inherit whatever default is configured there.

### Slack App

Create a bot to post invoice notifications and upload PDFs.

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** → **From scratch**
2. Name the app (e.g. "Invoicing Bot") and select your workspace
3. Go to **OAuth & Permissions** and add these **Bot Token Scopes**:
   - `chat:write` — post and delete messages
   - `files:write` — upload invoice PDFs
4. Click **Install to Workspace** and authorize
5. Copy the **Bot User OAuth Token** (`xoxb-...`) — this becomes `SLACK_BOT_TOKEN`
6. Invite the bot to your target channel: in Slack, open the channel and type `/invite @Invoicing Bot`
7. Set `SLACK_CHANNEL` to the channel name (e.g. `invoicing`)

## Getting Started

```bash
cp .env.example .env     # copy the template
# fill in the values from the setup steps above
# see .env.example for all available variables

uv sync                  # install dependencies
uv sync --group dev      # install dev dependencies (pytest)
```

## Usage

### Full pipeline (interactive terminal)

```bash
uv run python -m invoicing run --start 2026-03-01 --end 2026-03-31 --rate 100
```

Fetches hours, shows a preview, asks for approval, creates and finalizes the invoice, and sends a Slack notification.

> Use `--dry-run` to preview without creating anything.

### Step-by-step commands

Fetch hours from Clockify:

```bash
uv run python -m invoicing fetch --start 2026-03-01 --end 2026-03-31
```

Create a proforma invoice in Fakturoid:

```bash
uv run python -m invoicing create --start 2026-03-01 --end 2026-03-31 --rate 100
```

Finalize the proforma:

```bash
uv run python -m invoicing fire --invoice-id 123
```

Send a Slack notification (auto-fetches invoice details and uploads PDF):

```bash
uv run python -m invoicing notify --invoice-id 123
```

Or notify with manual details (text-only, no PDF):

```bash
uv run python -m invoicing notify \
  --invoice-number FV-123 --hours 10 --amount "1000 CZK" \
  --client "Acme" --period "2026-03-01 - 2026-03-31"
```

Delete a proforma if something went wrong:

```bash
uv run python -m invoicing delete --invoice-id 123
```

Delete a Slack bot message (and optional file):

```bash
uv run python -m invoicing slack-delete --ts 1234567890.123456 --file-id F0123ABC
```

All subcommands output JSON to stdout.

## Claude Code Skills

When using this project with [Claude Code](https://docs.anthropic.com/en/docs/claude-code), four slash commands are available:

| Command | Description |
|---------|-------------|
| `/preview` | Fetch hours and show a cost summary (read-only) |
| `/invoice` | Full pipeline — preview, approval, create, fire, notify |
| `/notify` | Send or re-send an invoice notification to Slack |
| `/yolo` | Invoice the last complete month, no questions asked |

**`/preview`** `[--start YYYY-MM-DD] [--end YYYY-MM-DD] [--rate N]`
Fetch hours from Clockify and display a cost summary. Read-only — no invoice is created.

**`/invoice`** `[--start YYYY-MM-DD] [--end YYYY-MM-DD] [--rate N] [--dry-run]`
Full pipeline: fetch hours → show preview → ask for approval → create proforma → fire → notify via Slack.

**`/notify`** `--invoice-id ID` or `--invoice-number FV-123 --hours 10 --amount "1000 CZK" --client "Acme" --period "..."`
Send or re-send an invoice notification to Slack. With `--invoice-id`, details and PDF are fetched automatically. The manual form sends a text-only message.

**`/yolo`** `[--rate N]`
Invoice the last complete calendar month — no preview, no approval. Fetches hours, creates and fires the invoice, and notifies via Slack in one shot.

> All commands default to the current month and `DEFAULT_HOURLY_RATE` from `.env` when arguments are omitted.

## Running Tests

```bash
uv run pytest
```
