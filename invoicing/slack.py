"""Slack incoming webhook notifier for invoice events."""

import logging

import httpx

logger = logging.getLogger(__name__)


async def send_invoice_notification(
    client: httpx.AsyncClient,
    webhook_url: str,
    invoice_number: str,
    total_amount: str,
    total_hours: float,
    period: str,
    client_name: str,
    invoice_url: str | None = None,
) -> None:
    """
    Send an invoice summary to a Slack channel via incoming webhook.

    This is a fallback for when Claude Code's MCP Slack tools are not
    available. When running interactively via Claude Code, prefer using
    the MCP slack_send_message tool directly.
    """
    text_parts = [
        f":white_check_mark: *Invoice #{invoice_number} issued*",
        f"Client: {client_name}",
        f"Period: {period}",
        f"Hours: {total_hours:.2f}",
        f"Total: {total_amount}",
    ]
    if invoice_url:
        text_parts.append(f"<{invoice_url}|View in Fakturoid>")

    resp = await client.post(webhook_url, json={"text": "\n".join(text_parts)})
    resp.raise_for_status()
    logger.info("Slack notification sent for invoice #%s", invoice_number)
