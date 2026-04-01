"""Slack Bot Token notifier with message posting and PDF file upload."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


def _escape_mrkdwn(text: str) -> str:
    """Escape Slack mrkdwn special characters to prevent injection."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _auth_headers(bot_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {bot_token}"}


async def resolve_channel_id(
    client: httpx.AsyncClient,
    bot_token: str,
    channel: str,
) -> str:
    """Resolve a channel name to its ID. Pass-through if already an ID."""
    if channel.startswith(("C", "G")) and channel[1:].isalnum():
        return channel
    resp = await client.get(
        f"{SLACK_API}/conversations.list",
        headers=_auth_headers(bot_token),
        params={"types": "public_channel,private_channel", "limit": "1000"},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack conversations.list failed: {data.get('error')}")
    for ch in data.get("channels", []):
        if ch.get("name") == channel:
            return ch["id"]
    raise RuntimeError(f"Slack channel not found: {channel}")


async def delete_message(
    client: httpx.AsyncClient,
    bot_token: str,
    channel: str,
    ts: str,
) -> dict[str, Any]:
    """Delete a bot message from a Slack channel via chat.delete."""
    channel_id = await resolve_channel_id(client, bot_token, channel)
    resp = await client.post(
        f"{SLACK_API}/chat.delete",
        headers={**_auth_headers(bot_token), "Content-Type": "application/json"},
        json={"channel": channel_id, "ts": ts},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.delete failed: {data.get('error')}")
    logger.info("Slack message deleted: channel=%s ts=%s", channel_id, ts)
    return data


async def delete_file(
    client: httpx.AsyncClient,
    bot_token: str,
    file_id: str,
) -> dict[str, Any]:
    """Delete a file from Slack via files.delete."""
    resp = await client.post(
        f"{SLACK_API}/files.delete",
        headers={**_auth_headers(bot_token), "Content-Type": "application/json"},
        json={"file": file_id},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack files.delete failed: {data.get('error')}")
    logger.info("Slack file deleted: %s", file_id)
    return data


async def post_message(
    client: httpx.AsyncClient,
    bot_token: str,
    channel: str,
    text: str,
) -> dict[str, Any]:
    """Post a text message to a Slack channel via chat.postMessage."""
    resp = await client.post(
        f"{SLACK_API}/chat.postMessage",
        headers={**_auth_headers(bot_token), "Content-Type": "application/json"},
        json={"channel": channel, "text": text},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage failed: {data.get('error')}")
    logger.info("Slack message posted to %s", channel)
    return data


async def upload_file(
    client: httpx.AsyncClient,
    bot_token: str,
    channel: str,
    filename: str,
    content: bytes,
    title: str,
) -> dict[str, Any]:
    """Upload a file to a Slack channel using the v2 upload flow."""
    # Step 1: get a presigned upload URL
    resp = await client.post(
        f"{SLACK_API}/files.getUploadURLExternal",
        headers=_auth_headers(bot_token),
        data={"filename": filename, "length": len(content)},
    )
    resp.raise_for_status()
    url_data = resp.json()
    if not url_data.get("ok"):
        raise RuntimeError(
            f"Slack getUploadURLExternal failed: {url_data.get('error')}"
        )

    upload_url = url_data["upload_url"]
    file_id = url_data["file_id"]

    # Validate upload URL to prevent SSRF via compromised API response
    if not upload_url.startswith("https://files.slack.com/"):
        raise RuntimeError(f"Unexpected Slack upload URL domain: {upload_url[:60]}")

    # Step 2: upload the bytes to the presigned URL
    resp = await client.post(
        upload_url,
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    resp.raise_for_status()

    # Step 3: complete the upload and share to channel
    resp = await client.post(
        f"{SLACK_API}/files.completeUploadExternal",
        headers={**_auth_headers(bot_token), "Content-Type": "application/json"},
        json={
            "files": [{"id": file_id, "title": title}],
            "channel_id": channel,
        },
    )
    resp.raise_for_status()
    complete_data = resp.json()
    if not complete_data.get("ok"):
        raise RuntimeError(
            f"Slack completeUploadExternal failed: {complete_data.get('error')}"
        )

    logger.info("Uploaded file %s to %s", filename, channel)
    complete_data["file_id"] = file_id
    return complete_data


async def send_invoice_notification(
    client: httpx.AsyncClient,
    bot_token: str,
    channel: str,
    invoice_number: str,
    total_amount: str,
    total_hours: float,
    period: str,
    client_name: str,
    invoice_url: str | None = None,
    pdf_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Send an invoice notification to Slack, optionally uploading the PDF.

    The text message is always sent. If pdf_bytes is provided, the PDF is
    uploaded as a follow-up. A PDF upload failure does not prevent the text
    notification from succeeding.
    """
    text_parts = [
        f":white_check_mark: *Invoice #{_escape_mrkdwn(invoice_number)} issued*",
        f"Client: {_escape_mrkdwn(client_name)}",
        f"Period: {_escape_mrkdwn(period)}",
        f"Hours: {total_hours:.2f}",
        f"Total: {_escape_mrkdwn(total_amount)}",
    ]
    if invoice_url:
        text_parts.append(f"<{invoice_url}|View in Fakturoid>")

    msg_data = await post_message(client, bot_token, channel, "\n".join(text_parts))
    channel_id = msg_data.get("channel", channel)
    result: dict[str, Any] = {
        "message_sent": True,
        "pdf_uploaded": False,
        "message_ts": msg_data.get("ts"),
        "channel_id": channel_id,
    }

    if pdf_bytes:
        try:
            upload_data = await upload_file(
                client,
                bot_token,
                channel_id,
                filename=f"invoice-{invoice_number}.pdf",
                content=pdf_bytes,
                title=f"Invoice #{invoice_number}",
            )
            result["pdf_uploaded"] = True
            result["file_id"] = upload_data.get("file_id")
        except Exception as exc:
            logger.warning("PDF upload failed (text notification was sent): %s", exc)
            result["pdf_error"] = str(exc)

    logger.info("Invoice notification sent for #%s", invoice_number)
    return result
