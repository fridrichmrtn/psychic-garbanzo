# PRD: Claude Code Tools Integration

## Vision

Turn the invoicing CLI into a first-class Claude Code experience — using **Skills**, **MCP servers**, and **agent orchestration** so that invoicing becomes a single conversational command rather than manual terminal work.

## Current State

- Python CLI with subcommands (`fetch`, `create`, `fire`, `delete`, `notify`)
- Designed for Claude Code orchestration (JSON output, step-by-step commands)
- Slack MCP available for notifications
- No custom skills, no custom MCP servers, no agent definitions

## Goals

1. **`/invoice` Skill** — One-command invoicing from Claude Code
2. **Custom MCP server** — Expose Clockify + Fakturoid as MCP tools (so Claude can call APIs directly without shelling out)
3. **Agent definitions** — Reusable agent configs in `.claude/agents/` for parallel work
4. **Robust error handling** — Graceful recovery, proforma cleanup on failure

---

## Feature 1: `/invoice` Skill

**File**: `.claude/skills/invoice.md`

A user-invocable skill that orchestrates the full invoicing workflow conversationally.

### Behavior

```
User: /invoice
Claude: Fetches hours from Clockify for the current month...
        Found 42.5 hours across 3 projects.
        Rate: 1,500 CZK/hr → Subtotal: 63,750 CZK + VAT 21% = 77,137 CZK
        Client: Acme Corp

        Create this invoice?
User: yes
Claude: Proforma created (#FV-2026-042). Finalizing...
        Invoice fired. Sending Slack notification to #invoicing...
        Done. Invoice FV-2026-042 issued for 77,137 CZK.
```

### Skill Prompt Should

- Default to current month if no dates given
- Use `uv run python -m invoicing fetch` to get hours
- Present a preview and wait for user approval before creating
- Use `uv run python -m invoicing create` + `fire` for the Fakturoid steps
- Use MCP `slack_send_message` for notification (not webhook)
- Handle edge cases: zero hours, API errors, user cancellation
- Support `--dry-run` equivalent (just preview, no invoice)

---

## Feature 2: Custom MCP Server (Clockify + Fakturoid)

**Directory**: `mcp/` or `invoicing/mcp_server.py`

Expose the invoicing APIs as MCP tools so Claude can call them directly — no shell needed, better error handling, typed parameters.

### Tools to Expose

| Tool | Description | Parameters |
|------|-------------|------------|
| `clockify_fetch_hours` | Fetch time entries for a period | `start_date`, `end_date` |
| `fakturoid_create_proforma` | Create a proforma invoice | `subject_name`, `hours`, `rate`, `vat_rate`, `period` |
| `fakturoid_fire_invoice` | Finalize a proforma | `invoice_id` |
| `fakturoid_delete_invoice` | Delete a proforma | `invoice_id` |
| `fakturoid_list_invoices` | List recent invoices | `page`, `status` |

### Implementation Notes

- Use the MCP Python SDK (`mcp` package)
- Reuse existing `clockify.py` and `fakturoid.py` modules
- Register in `.claude/settings.json` under `mcpServers`
- Auth via environment variables (same `.env`)

---

## Feature 3: Agent Definitions

**Directory**: `.claude/agents/`

### `invoicing-agent.md`

A specialized agent that knows the invoicing domain. Can be spawned by the team lead for invoicing tasks.

- Has access to the `/invoice` skill context
- Knows the Clockify/Fakturoid/Slack workflow
- Can run CLI commands and use MCP tools
- Handles the approval flow with the user

### `auditor-agent.md`

A read-only agent for reviewing invoices and time entries.

- Can fetch hours and list invoices but cannot create/fire/delete
- Useful for month-end reconciliation
- Can compare Clockify hours vs. Fakturoid invoices

---

## Feature 4: Settings & Hooks

**File**: `.claude/settings.json`

```jsonc
{
  "permissions": {
    "allow": [
      "Bash(uv run python -m invoicing *)",
      "Bash(uv sync*)"
    ]
  },
  "mcpServers": {
    // Registered after Feature 2 is built
  }
}
```

### Hooks (Future)

- **Pre-fire hook**: Validate invoice total against expected range before finalizing
- **Post-notify hook**: Log invoice details to a local CSV/JSON ledger

---

## Implementation Order

Recommended sequence for parallel agent work:

| Phase | Feature | Depends On | Parallelizable |
|-------|---------|------------|----------------|
| 1a | `/invoice` skill | nothing | yes |
| 1b | `.claude/settings.json` | nothing | yes |
| 1c | Agent definitions | nothing | yes |
| 2 | MCP server | existing modules | after 1b |
| 3 | Hooks | MCP server | after 2 |

**Phases 1a, 1b, 1c** can all be done in parallel by different agents.

---

## Out of Scope (For Now)

- Multi-client invoicing (currently single `FAKTUROID_SUBJECT_NAME`)
- Recurring/scheduled invoicing (cron-like)
- Invoice PDF download/attachment
- Fakturoid webhook integration (push notifications)
- Time entry approval/editing in Clockify
