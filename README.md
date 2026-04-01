# psychic-garbanzo — Invoicing Automation

Freelance invoicing pipeline: **Clockify** (time tracking) → **Fakturoid** (Czech invoicing) → **Slack** (notification).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Accounts on [Clockify](https://clockify.me), [Fakturoid](https://www.fakturoid.cz), and [Slack](https://slack.com)

## Service Setup

### Clockify

1. Log in to [Clockify](https://clockify.me)
2. Go to **Profile Settings** → **API** → generate an API key
3. Copy the key — this becomes `CLOCKIFY_API_KEY`

### Fakturoid

1. Log in to [Fakturoid](https://app.fakturoid.cz)
2. Go to **Settings** → **Developer** → **OAuth Apps** → create a new app
3. Copy the **Client ID** and **Client Secret** — these become `FAKTUROID_CLIENT_ID` and `FAKTUROID_CLIENT_SECRET`
4. Note your account slug (the subdomain in your Fakturoid URL, e.g. `martinfridrich`) — this becomes `FAKTUROID_SLUG`
5. Set `FAKTUROID_SUBJECT_NAME` to the client company name that invoices are issued to

### Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** → **From scratch**
2. Name the app (e.g. "Invoicing Bot") and select your workspace
3. Go to **OAuth & Permissions** and add these **Bot Token Scopes**:
   - `chat:write` — post and delete messages
   - `files:write` — upload invoice PDFs
4. Click **Install to Workspace** and authorize
5. Copy the **Bot User OAuth Token** (`xoxb-...`) — this becomes `SLACK_BOT_TOKEN`
6. Invite the bot to your target channel: in Slack, open the channel and type `/invite @Invoicing Bot`
7. Set `SLACK_CHANNEL` to the channel name (e.g. `invoicing`)

## Configuration

```bash
cp .env.example .env
```

Fill in the values from the setup steps above. See `.env.example` for all available variables.

## Installation

```bash
uv sync                  # install dependencies
uv sync --group dev      # install dev dependencies (pytest)
```

## Usage

### Full pipeline (interactive terminal)

```bash
uv run python -m invoicing run --start 2026-03-01 --end 2026-03-31 --rate 100
```

This fetches hours, shows a preview, asks for approval, creates and finalizes the invoice, and sends a Slack notification.

Add `--dry-run` to preview without creating anything.

### Step-by-step (for scripting or Claude Code orchestration)

```bash
# 1. Fetch hours from Clockify
uv run python -m invoicing fetch --start 2026-03-01 --end 2026-03-31

# 2. Create proforma invoice in Fakturoid
uv run python -m invoicing create --start 2026-03-01 --end 2026-03-31 --rate 100

# 3. Finalize the proforma
uv run python -m invoicing fire --invoice-id 123

# 4. Send Slack notification (auto-fetches invoice details)
uv run python -m invoicing notify --invoice-id 123

# Or notify with manual details
uv run python -m invoicing notify \
  --invoice-number FV-123 --hours 10 --amount "1000 CZK" \
  --client "Acme" --period "2026-03-01 - 2026-03-31"

# Delete a proforma if something went wrong
uv run python -m invoicing delete --invoice-id 123

# Delete a bot message (and optional file) from Slack
uv run python -m invoicing slack-delete --ts 1234567890.123456
uv run python -m invoicing slack-delete --ts 1234567890.123456 --file-id F0123ABC
```

All subcommands output JSON to stdout.

## Running Tests

```bash
uv run pytest
```
