"""CLI entry point for the invoicing workflow.

Supports two modes of use:

1. Standalone pipeline (terminal):
   uv run python -m invoicing --start 2026-03-01 --end 2026-03-31 --rate 100

2. Individual steps (Claude Code orchestration):
   uv run python -m invoicing fetch --start 2026-03-01 --end 2026-03-31
   uv run python -m invoicing create --start 2026-03-01 --end 2026-03-31 --rate 100
   uv run python -m invoicing fire --invoice-id 123
   uv run python -m invoicing delete --invoice-id 123
   uv run python -m invoicing notify --invoice-id 123
   uv run python -m invoicing notify --invoice-number FV-123 --hours 10 --amount "1000 CZK" --client "Acme" --period "2026-03-01 - 2026-03-31"
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime

import httpx

from invoicing.config import InvoicingSettings
from invoicing.fakturoid import (
    delete_invoice,
    download_pdf,
    fire_invoice,
    get_invoice,
    get_oauth_token,
    get_subject,
)
from invoicing.slack import delete_file, delete_message, send_invoice_notification
from invoicing.workflows import (
    build_fakturoid_url,
    create_invoice_draft,
    fetch_summary,
    format_total_amount,
    hours_by_project,
    require_rate,
    summary_to_output,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_invoice_lines(
    by_project: dict[str, float],
    rate: float,
    vat_rate: int,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """Build Fakturoid invoice line items with per-project breakdown."""
    return [
        {
            "name": f"{project} ({period_start} — {period_end})",
            "quantity": hours,
            "unit_name": "hrs",
            "unit_price": rate,
            "vat_rate": vat_rate,
        }
        for project, hours in by_project.items()
    ]


def format_preview(
    client_name: str,
    period: str,
    hours: float,
    rate: float,
    vat_rate: int,
    invoice_number: str | None = None,
) -> str:
    """Build a terminal-friendly invoice preview."""
    subtotal = hours * rate
    vat = subtotal * vat_rate / 100
    total = subtotal + vat
    num_line = f"  Number:   {invoice_number}" if invoice_number else ""
    lines = [
        "",
        "  ┌─────────────────────────────────────┐",
        "  │  INVOICE PREVIEW                     │",
        "  ├─────────────────────────────────────┤",
        f"  │  Client:   {client_name:<25}│",
        f"  │  Period:   {period:<25}│",
    ]
    if num_line:
        lines.append(f"  │{num_line:<37}│")
    lines.extend(
        [
            f"  │  Hours:    {hours:<25.2f}│",
            f"  │  Rate:     {rate:,.0f} CZK/hr{'':<16}│",
            f"  │  Subtotal: {subtotal:,.0f} CZK{'':<18}│",
            f"  │  VAT {vat_rate}%:  {vat:,.0f} CZK{'':<18}│",
            f"  │  Total:    {total:,.0f} CZK{'':<18}│",
            "  └─────────────────────────────────────┘",
            "",
        ]
    )
    return "\n".join(lines)


def prompt_approval() -> bool:
    """Ask the user to approve the invoice. Returns True if approved."""
    try:
        answer = (
            input("[3/4] Approve and finalize this invoice? [y/N]: ").strip().lower()
        )
        return answer == "y"
    except (EOFError, KeyboardInterrupt):
        return False


async def _get_token(client: httpx.AsyncClient, settings: InvoicingSettings) -> str:
    """Obtain a Fakturoid OAuth token from settings."""
    return await get_oauth_token(
        client,
        settings.fakturoid_base_url,
        settings.fakturoid_client_id,
        settings.fakturoid_client_secret,
    )


# ---------------------------------------------------------------------------
# Subcommand handlers (for step-by-step Claude Code orchestration)
# ---------------------------------------------------------------------------


async def cmd_fetch(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Fetch and display time entries from Clockify."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        summary = await fetch_summary(client, settings, args.start, args.end)

    print(json.dumps(summary_to_output(summary), indent=2, ensure_ascii=False))


async def cmd_create(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Create a proforma invoice in Fakturoid."""
    try:
        rate = require_rate(args.rate, settings.default_hourly_rate)
    except ValueError:
        print(
            "Error: hourly rate must be positive. Use --rate or set DEFAULT_HOURLY_RATE.",
            file=sys.stderr,
        )
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        summary = await fetch_summary(client, settings, args.start, args.end)
        if summary.total_hours == 0:
            print(json.dumps({"error": "No billable hours found"}))
            sys.exit(0)

        lines = build_invoice_lines(
            hours_by_project(summary),
            rate,
            settings.default_vat_rate,
            summary.period_start,
            summary.period_end,
        )
        draft = await create_invoice_draft(
            client,
            settings,
            summary,
            rate,
            lines,
        )

    # Output for Claude Code to pick up
    print(
        json.dumps(
            {
                "invoice_id": draft.invoice["id"],
                "invoice_number": draft.invoice.get("number"),
                "subject_name": draft.subject["name"],
                "total_hours": draft.summary.total_hours,
                "rate": rate,
                "vat_rate": settings.default_vat_rate,
                "subtotal": str(draft.invoice.get("subtotal", "")),
                "total": str(draft.invoice.get("total", "")),
                "status": "proforma",
                "fakturoid_url": build_fakturoid_url(
                    settings.fakturoid_base_url,
                    settings.fakturoid_slug,
                    draft.invoice["id"],
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


async def cmd_fire(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Finalize a proforma invoice."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        token = await _get_token(client, settings)
        invoice = await get_invoice(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            args.invoice_id,
        )
        if invoice.get("document_type") == "invoice":
            print(
                json.dumps({"invoice_id": args.invoice_id, "status": "already_fired"})
            )
            return
        await fire_invoice(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            args.invoice_id,
        )
    print(json.dumps({"invoice_id": args.invoice_id, "status": "fired"}))


async def cmd_delete(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Delete a proforma invoice."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        token = await _get_token(client, settings)
        await delete_invoice(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            args.invoice_id,
        )
    print(json.dumps({"invoice_id": args.invoice_id, "status": "deleted"}))


async def cmd_notify(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Send invoice notification to Slack."""
    if not settings.slack_bot_token:
        print("Error: SLACK_BOT_TOKEN not set.", file=sys.stderr)
        sys.exit(1)
    if not settings.slack_channel:
        print("Error: SLACK_CHANNEL not set.", file=sys.stderr)
        sys.exit(1)

    invoice_id = getattr(args, "invoice_id", None)
    if not invoice_id:
        missing = [
            f
            for f in ("invoice_number", "amount", "hours", "period", "client")
            if not getattr(args, f, None)
        ]
        if missing:
            print(
                f"Error: provide --invoice-id or all manual args. Missing: {', '.join('--' + f.replace('_', '-') for f in missing)}",
                file=sys.stderr,
            )
            sys.exit(1)

    pdf_bytes: bytes | None = None
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        if invoice_id:
            # Lookup mode: fetch invoice details from Fakturoid
            token = await _get_token(client, settings)
            invoice = await get_invoice(
                client,
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                token,
                settings.fakturoid_user_agent,
                invoice_id,
            )
            subject = await get_subject(
                client,
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                token,
                settings.fakturoid_user_agent,
                invoice["subject_id"],
            )
            # Sum hours across all invoice lines
            lines = invoice.get("lines", [])
            total_hours = sum(float(line.get("quantity", 0)) for line in lines)
            invoice_number = str(invoice.get("number", ""))
            total_amount = f"{invoice.get('total', '')} CZK"
            client_name = subject["name"]
            period = invoice.get("issued_on", "")
            invoice_url = build_fakturoid_url(
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                invoice["id"],
            )
            # Download PDF (best-effort)
            try:
                pdf_bytes = await download_pdf(
                    client,
                    settings.fakturoid_base_url,
                    settings.fakturoid_slug,
                    token,
                    settings.fakturoid_user_agent,
                    invoice["id"],
                )
            except httpx.HTTPError as exc:
                logger.warning("Could not download PDF: %s", exc)
        else:
            invoice_number = args.invoice_number
            total_amount = args.amount
            total_hours = args.hours
            client_name = args.client
            period = args.period
            invoice_url = None

        notify_kwargs = dict(
            invoice_number=invoice_number,
            total_amount=total_amount,
            total_hours=total_hours,
            period=period,
            client_name=client_name,
            invoice_url=invoice_url,
            pdf_bytes=pdf_bytes,
        )
        result = await send_invoice_notification(
            client,
            settings.slack_bot_token,
            settings.slack_channel,
            **notify_kwargs,
        )
    print(
        json.dumps(
            {
                "status": "notified",
                "pdf_uploaded": result.get("pdf_uploaded", False),
                "message_ts": result.get("message_ts"),
                "channel_id": result.get("channel_id"),
            }
        )
    )


async def cmd_slack_delete(
    args: argparse.Namespace, settings: InvoicingSettings
) -> None:
    """Delete a bot message from Slack."""
    if not settings.slack_bot_token:
        print("Error: SLACK_BOT_TOKEN not set.", file=sys.stderr)
        sys.exit(1)
    if not settings.slack_channel:
        print("Error: SLACK_CHANNEL not set.", file=sys.stderr)
        sys.exit(1)

    channel = args.channel_id or settings.slack_channel
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await delete_message(
            client,
            settings.slack_bot_token,
            channel,
            args.ts,
        )
        if args.file_id:
            await delete_file(client, settings.slack_bot_token, args.file_id)
    result = {"status": "deleted", "channel": channel, "ts": args.ts}
    if args.file_id:
        result["file_id"] = args.file_id
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# Full pipeline (standalone terminal mode)
# ---------------------------------------------------------------------------


async def cmd_run(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Run the full invoicing pipeline with terminal approval prompt."""
    try:
        rate = require_rate(args.rate, settings.default_hourly_rate)
    except ValueError:
        logger.error(
            "Hourly rate must be positive. Set --rate or DEFAULT_HOURLY_RATE in .env"
        )
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Step 1: Clockify
        print("\n[1/4] Fetching time entries from Clockify...")
        summary = await fetch_summary(client, settings, args.start, args.end)
        print(
            f"  Found {len(summary.entries)} entries totalling {summary.total_hours:.2f} hours"
        )

        if summary.total_hours == 0:
            print("  No billable hours found. Exiting.")
            sys.exit(0)

        if args.dry_run:
            print(
                format_preview(
                    settings.fakturoid_subject_name,
                    f"{args.start} to {args.end}",
                    summary.total_hours,
                    rate,
                    settings.default_vat_rate,
                )
            )
            print("  [DRY RUN] No invoice created.")
            sys.exit(0)

        # Step 2: Fakturoid — create proforma
        print("\n[2/4] Creating proforma invoice in Fakturoid...")
        lines = build_invoice_lines(
            hours_by_project(summary),
            rate,
            settings.default_vat_rate,
            summary.period_start,
            summary.period_end,
        )
        draft = await create_invoice_draft(
            client,
            settings,
            summary,
            rate,
            lines,
        )
        print(f"  Subject: {draft.subject['name']} (id={draft.subject['id']})")
        print(
            format_preview(
                draft.subject["name"],
                f"{args.start} to {args.end}",
                draft.summary.total_hours,
                rate,
                settings.default_vat_rate,
                invoice_number=draft.invoice.get("number"),
            )
        )

        # Step 3: Human approval
        if prompt_approval():
            await fire_invoice(
                client,
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                draft.token,
                settings.fakturoid_user_agent,
                draft.invoice["id"],
            )
            print(f"  Invoice #{draft.invoice.get('number')} finalized.")
        else:
            print("  Rejected. Deleting proforma...")
            await delete_invoice(
                client,
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                draft.token,
                settings.fakturoid_user_agent,
                draft.invoice["id"],
            )
            print("  Proforma deleted.")
            sys.exit(0)

        # Step 4: Slack notification
        if settings.slack_bot_token and settings.slack_channel:
            print("\n[4/4] Sending Slack notification...")
            try:
                invoice_url = build_fakturoid_url(
                    settings.fakturoid_base_url,
                    settings.fakturoid_slug,
                    draft.invoice["id"],
                )
                pdf_bytes: bytes | None = None
                try:
                    pdf_bytes = await download_pdf(
                        client,
                        settings.fakturoid_base_url,
                        settings.fakturoid_slug,
                        draft.token,
                        settings.fakturoid_user_agent,
                        draft.invoice["id"],
                    )
                except httpx.HTTPError as exc:
                    logger.warning("Could not download PDF: %s", exc)
                result = await send_invoice_notification(
                    client,
                    settings.slack_bot_token,
                    settings.slack_channel,
                    invoice_number=str(draft.invoice.get("number", "")),
                    total_amount=format_total_amount(draft.summary.total_hours, rate),
                    total_hours=draft.summary.total_hours,
                    period=f"{args.start} — {args.end}",
                    client_name=draft.subject["name"],
                    invoice_url=invoice_url,
                    pdf_bytes=pdf_bytes,
                )
                print(
                    f"  Notification sent (PDF uploaded: {result.get('pdf_uploaded', False)})."
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                logger.warning(
                    "Slack notification failed (invoice was still created): %s", exc
                )
        else:
            print(
                "\n[4/4] No SLACK_BOT_TOKEN/SLACK_CHANNEL set — skipping notification."
            )

    print("\nDone.")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _valid_date(value: str) -> str:
    """Validate that value is a YYYY-MM-DD date string."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: '{value}'. Expected YYYY-MM-DD."
        )
    return value


def _positive_float(value: str) -> float:
    """Validate that value is a positive number."""
    f = float(value)
    if f <= 0:
        raise argparse.ArgumentTypeError(f"Rate must be positive, got {f}")
    return f


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="invoicing",
        description="Invoicing automation: Clockify -> Fakturoid -> Slack",
    )
    sub = parser.add_subparsers(dest="command")

    # Default: full pipeline
    run_p = sub.add_parser("run", help="Full pipeline with terminal approval")
    run_p.add_argument(
        "--start", required=True, type=_valid_date, help="Period start (YYYY-MM-DD)"
    )
    run_p.add_argument(
        "--end", required=True, type=_valid_date, help="Period end (YYYY-MM-DD)"
    )
    run_p.add_argument("--rate", type=_positive_float, help="Hourly rate in CZK")
    run_p.add_argument(
        "--dry-run", action="store_true", help="Preview only, no invoice"
    )

    # Step: fetch time entries
    fetch_p = sub.add_parser("fetch", help="Fetch Clockify time entries (JSON)")
    fetch_p.add_argument(
        "--start", required=True, type=_valid_date, help="Period start (YYYY-MM-DD)"
    )
    fetch_p.add_argument(
        "--end", required=True, type=_valid_date, help="Period end (YYYY-MM-DD)"
    )

    # Step: create proforma
    create_p = sub.add_parser("create", help="Create proforma invoice in Fakturoid")
    create_p.add_argument(
        "--start", required=True, type=_valid_date, help="Period start (YYYY-MM-DD)"
    )
    create_p.add_argument(
        "--end", required=True, type=_valid_date, help="Period end (YYYY-MM-DD)"
    )
    create_p.add_argument("--rate", type=_positive_float, help="Hourly rate in CZK")

    # Step: fire (finalize)
    fire_p = sub.add_parser("fire", help="Finalize a proforma invoice")
    fire_p.add_argument("--invoice-id", type=int, required=True)

    # Step: delete
    del_p = sub.add_parser("delete", help="Delete a proforma invoice")
    del_p.add_argument("--invoice-id", type=int, required=True)

    # Step: notify (two modes: --invoice-id for auto-lookup, or manual args)
    notify_p = sub.add_parser(
        "notify", help="Send Slack notification with optional PDF"
    )
    notify_p.add_argument(
        "--invoice-id", type=int, help="Fakturoid invoice ID (auto-fetches details)"
    )
    notify_p.add_argument("--invoice-number", help="Invoice number (manual mode)")
    notify_p.add_argument("--amount", help='e.g. "1000 CZK" (manual mode)')
    notify_p.add_argument("--hours", type=float, help="Total hours (manual mode)")
    notify_p.add_argument(
        "--period", help='e.g. "2026-03-01 - 2026-03-31" (manual mode)'
    )
    notify_p.add_argument("--client", help="Client name (manual mode)")

    # Step: slack-delete
    sdel_p = sub.add_parser("slack-delete", help="Delete a bot message from Slack")
    sdel_p.add_argument("--ts", required=True, help="Message timestamp to delete")
    sdel_p.add_argument("--channel-id", help="Channel ID (skips channel resolution)")
    sdel_p.add_argument("--file-id", help="File ID to delete along with the message")

    return parser


COMMANDS = {
    "run": cmd_run,
    "fetch": cmd_fetch,
    "create": cmd_create,
    "fire": cmd_fire,
    "delete": cmd_delete,
    "notify": cmd_notify,
    "slack-delete": cmd_slack_delete,
}


async def main() -> None:
    """Parse args and dispatch to the appropriate handler."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        settings = InvoicingSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        logger.error(
            "Check your .env file has the required CLOCKIFY_* and FAKTUROID_* variables."
        )
        sys.exit(1)

    handler = COMMANDS[args.command]
    try:
        await handler(args, settings)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "API request failed: %s %s -> %d",
            exc.request.method,
            exc.request.url,
            exc.response.status_code,
        )
        logger.error("Response status: %d", exc.response.status_code)
        sys.exit(1)
    except ValueError as exc:
        logger.error("Error: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


if __name__ == "__main__":
    asyncio.run(main())
