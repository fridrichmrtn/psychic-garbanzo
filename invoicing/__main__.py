"""CLI entry point for the invoicing workflow.

Supports two modes of use:

1. Standalone pipeline (terminal):
   uv run python -m invoicing --start 2026-03-01 --end 2026-03-31 --rate 1500

2. Individual steps (Claude Code orchestration):
   uv run python -m invoicing fetch --start 2026-03-01 --end 2026-03-31
   uv run python -m invoicing create --start 2026-03-01 --end 2026-03-31 --rate 1500
   uv run python -m invoicing fire --invoice-id 12345
   uv run python -m invoicing delete --invoice-id 12345
   uv run python -m invoicing notify --invoice-id 12345 --hours 42.5 --amount "63750 CZK" --client "Acme" --period "2026-03-01 - 2026-03-31"
"""

import argparse
import asyncio
import json
import logging
import sys

import httpx

from invoicing.clockify import fetch_time_entries
from invoicing.config import InvoicingSettings
from invoicing.fakturoid import (
    create_proforma_invoice,
    delete_invoice,
    find_subject,
    fire_invoice,
    get_oauth_token,
)
from invoicing.slack import send_invoice_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_invoice_lines(
    total_hours: float,
    rate: float,
    vat_rate: int,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """Build Fakturoid invoice line items from time summary."""
    return [
        {
            "name": f"Consulting services ({period_start} — {period_end})",
            "quantity": total_hours,
            "unit_name": "hrs",
            "unit_price": rate,
            "vat_rate": vat_rate,
        }
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
        answer = input("[3/4] Approve and finalize this invoice? [y/N]: ").strip().lower()
        return answer == "y"
    except (EOFError, KeyboardInterrupt):
        return False


# ---------------------------------------------------------------------------
# Subcommand handlers (for step-by-step Claude Code orchestration)
# ---------------------------------------------------------------------------


async def cmd_fetch(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Fetch and display time entries from Clockify."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        summary = await fetch_time_entries(
            client,
            settings.clockify_api_key,
            settings.clockify_base_url,
            args.start,
            args.end,
        )

    # Output as JSON for easy parsing by Claude Code
    output = {
        "total_hours": summary.total_hours,
        "entry_count": len(summary.entries),
        "period_start": summary.period_start,
        "period_end": summary.period_end,
        "by_project": {},
        "entries": [],
    }
    for entry in summary.entries:
        proj = entry.project_name or "(no project)"
        output["by_project"].setdefault(proj, 0.0)
        output["by_project"][proj] = round(
            output["by_project"][proj] + entry.duration_hours, 2
        )
        output["entries"].append(
            {
                "description": entry.description,
                "project": entry.project_name,
                "hours": entry.duration_hours,
                "date": entry.start.strftime("%Y-%m-%d"),
                "billable": entry.billable,
            }
        )

    print(json.dumps(output, indent=2, ensure_ascii=False))


async def cmd_create(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Create a proforma invoice in Fakturoid."""
    rate = args.rate or settings.default_hourly_rate
    if rate <= 0:
        print("Error: hourly rate must be positive. Use --rate or set DEFAULT_HOURLY_RATE.", file=sys.stderr)
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch hours
        summary = await fetch_time_entries(
            client,
            settings.clockify_api_key,
            settings.clockify_base_url,
            args.start,
            args.end,
        )
        if summary.total_hours == 0:
            print(json.dumps({"error": "No billable hours found"}))
            sys.exit(0)

        # Fakturoid auth + subject lookup
        token = await get_oauth_token(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_client_id,
            settings.fakturoid_client_secret,
        )
        subject = await find_subject(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            settings.fakturoid_subject_name,
        )
        lines = build_invoice_lines(
            summary.total_hours,
            rate,
            settings.default_vat_rate,
            summary.period_start,
            summary.period_end,
        )
        invoice = await create_proforma_invoice(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            subject["id"],
            lines,
        )

    # Output for Claude Code to pick up
    print(
        json.dumps(
            {
                "invoice_id": invoice["id"],
                "invoice_number": invoice.get("number"),
                "subject_name": subject["name"],
                "total_hours": summary.total_hours,
                "rate": rate,
                "vat_rate": settings.default_vat_rate,
                "subtotal": str(invoice.get("subtotal", "")),
                "total": str(invoice.get("total", "")),
                "status": "proforma",
                "fakturoid_url": f"{settings.fakturoid_base_url}/i/{settings.fakturoid_slug}/{invoice['id']}",
            },
            indent=2,
            ensure_ascii=False,
        )
    )


async def cmd_fire(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Finalize a proforma invoice."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await get_oauth_token(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_client_id,
            settings.fakturoid_client_secret,
        )
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        token = await get_oauth_token(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_client_id,
            settings.fakturoid_client_secret,
        )
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
    """Send invoice notification to Slack via webhook."""
    if not settings.slack_webhook_url:
        print("Error: SLACK_WEBHOOK_URL not set. Use MCP Slack tools instead.", file=sys.stderr)
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        await send_invoice_notification(
            client,
            settings.slack_webhook_url,
            invoice_number=args.invoice_number,
            total_amount=args.amount,
            total_hours=args.hours,
            period=args.period,
            client_name=args.client,
        )
    print(json.dumps({"status": "notified"}))


# ---------------------------------------------------------------------------
# Full pipeline (standalone terminal mode)
# ---------------------------------------------------------------------------


async def cmd_run(args: argparse.Namespace, settings: InvoicingSettings) -> None:
    """Run the full invoicing pipeline with terminal approval prompt."""
    rate = args.rate or settings.default_hourly_rate
    if rate <= 0:
        logger.error("Hourly rate must be positive. Set --rate or DEFAULT_HOURLY_RATE in .env")
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Clockify
        print("\n[1/4] Fetching time entries from Clockify...")
        summary = await fetch_time_entries(
            client,
            settings.clockify_api_key,
            settings.clockify_base_url,
            args.start,
            args.end,
        )
        print(f"  Found {len(summary.entries)} entries totalling {summary.total_hours:.2f} hours")

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
        token = await get_oauth_token(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_client_id,
            settings.fakturoid_client_secret,
        )
        subject = await find_subject(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            settings.fakturoid_subject_name,
        )
        lines = build_invoice_lines(
            summary.total_hours,
            rate,
            settings.default_vat_rate,
            summary.period_start,
            summary.period_end,
        )
        invoice = await create_proforma_invoice(
            client,
            settings.fakturoid_base_url,
            settings.fakturoid_slug,
            token,
            settings.fakturoid_user_agent,
            subject["id"],
            lines,
        )
        print(f"  Subject: {subject['name']} (id={subject['id']})")
        print(
            format_preview(
                subject["name"],
                f"{args.start} to {args.end}",
                summary.total_hours,
                rate,
                settings.default_vat_rate,
                invoice_number=invoice.get("number"),
            )
        )

        # Step 3: Human approval
        if prompt_approval():
            await fire_invoice(
                client,
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                token,
                settings.fakturoid_user_agent,
                invoice["id"],
            )
            print(f"  Invoice #{invoice.get('number')} finalized.")
        else:
            print("  Rejected. Deleting proforma...")
            await delete_invoice(
                client,
                settings.fakturoid_base_url,
                settings.fakturoid_slug,
                token,
                settings.fakturoid_user_agent,
                invoice["id"],
            )
            print("  Proforma deleted.")
            sys.exit(0)

        # Step 4: Slack notification
        if settings.slack_webhook_url:
            print("\n[4/4] Sending Slack notification...")
            try:
                invoice_url = f"{settings.fakturoid_base_url}/i/{settings.fakturoid_slug}/{invoice['id']}"
                await send_invoice_notification(
                    client,
                    settings.slack_webhook_url,
                    invoice_number=str(invoice.get("number", "")),
                    total_amount=f"{summary.total_hours * rate:,.0f} CZK",
                    total_hours=summary.total_hours,
                    period=f"{args.start} — {args.end}",
                    client_name=subject["name"],
                    invoice_url=invoice_url,
                )
                print("  Notification sent.")
            except Exception as exc:
                logger.warning("Slack notification failed (invoice was still created): %s", exc)
        else:
            print("\n[4/4] No SLACK_WEBHOOK_URL set — skipping notification.")
            print("  (Use Claude Code MCP Slack tools to post manually.)")

    print("\nDone.")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="invoicing",
        description="Invoicing automation: Clockify -> Fakturoid -> Slack",
    )
    sub = parser.add_subparsers(dest="command")

    # Default: full pipeline
    run_p = sub.add_parser("run", help="Full pipeline with terminal approval")
    run_p.add_argument("--start", required=True, help="Period start (YYYY-MM-DD)")
    run_p.add_argument("--end", required=True, help="Period end (YYYY-MM-DD)")
    run_p.add_argument("--rate", type=float, help="Hourly rate in CZK")
    run_p.add_argument("--dry-run", action="store_true", help="Preview only, no invoice")

    # Step: fetch time entries
    fetch_p = sub.add_parser("fetch", help="Fetch Clockify time entries (JSON)")
    fetch_p.add_argument("--start", required=True, help="Period start (YYYY-MM-DD)")
    fetch_p.add_argument("--end", required=True, help="Period end (YYYY-MM-DD)")

    # Step: create proforma
    create_p = sub.add_parser("create", help="Create proforma invoice in Fakturoid")
    create_p.add_argument("--start", required=True, help="Period start (YYYY-MM-DD)")
    create_p.add_argument("--end", required=True, help="Period end (YYYY-MM-DD)")
    create_p.add_argument("--rate", type=float, help="Hourly rate in CZK")

    # Step: fire (finalize)
    fire_p = sub.add_parser("fire", help="Finalize a proforma invoice")
    fire_p.add_argument("--invoice-id", type=int, required=True)

    # Step: delete
    del_p = sub.add_parser("delete", help="Delete a proforma invoice")
    del_p.add_argument("--invoice-id", type=int, required=True)

    # Step: notify
    notify_p = sub.add_parser("notify", help="Send Slack webhook notification")
    notify_p.add_argument("--invoice-number", required=True)
    notify_p.add_argument("--amount", required=True, help='e.g. "63750 CZK"')
    notify_p.add_argument("--hours", type=float, required=True)
    notify_p.add_argument("--period", required=True, help='e.g. "2026-03-01 - 2026-03-31"')
    notify_p.add_argument("--client", required=True, help="Client name")

    return parser


COMMANDS = {
    "run": cmd_run,
    "fetch": cmd_fetch,
    "create": cmd_create,
    "fire": cmd_fire,
    "delete": cmd_delete,
    "notify": cmd_notify,
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
        logger.error("Check your .env file has the required CLOCKIFY_* and FAKTUROID_* variables.")
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
        logger.error("Response: %s", exc.response.text[:500])
        sys.exit(1)
    except ValueError as exc:
        logger.error("Error: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


if __name__ == "__main__":
    asyncio.run(main())
