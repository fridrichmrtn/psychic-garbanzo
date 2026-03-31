"""Fakturoid API client for invoice creation and management."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _headers(token: str, user_agent: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": user_agent,
    }


async def get_oauth_token(
    client: httpx.AsyncClient,
    base_url: str,
    client_id: str,
    client_secret: str,
) -> str:
    """
    Obtain an OAuth2 access token using client credentials.

    Returns:
        Bearer token string.
    """
    resp = await client.post(
        f"{base_url}/api/v3/oauth/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    logger.info("Fakturoid OAuth token acquired")
    return token


async def find_subject(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    query: str,
) -> dict[str, Any]:
    """
    Search for an invoicing subject (client) by name.

    Returns:
        First matching subject dict.

    Raises:
        ValueError: if no subject matches the query.
    """
    resp = await client.get(
        f"{base_url}/api/v3/accounts/{slug}/subjects/search.json",
        headers=_headers(token, user_agent),
        params={"query": query},
    )
    resp.raise_for_status()
    subjects = resp.json()
    if not subjects:
        raise ValueError(f"No Fakturoid subject found matching '{query}'")
    logger.info(
        "Found subject: %s (id=%s)", subjects[0]["name"], subjects[0]["id"]
    )
    return subjects[0]


async def create_proforma_invoice(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    subject_id: int,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Create a proforma (draft) invoice in Fakturoid.

    The proforma has a real invoice number but is not yet a tax document.
    Call fire_invoice() after approval to convert it.

    Returns:
        Created invoice dict from Fakturoid API.
    """
    headers = {**_headers(token, user_agent), "Content-Type": "application/json"}
    payload = {
        "subject_id": subject_id,
        "proforma": True,
        "lines": lines,
    }
    resp = await client.post(
        f"{base_url}/api/v3/accounts/{slug}/invoices.json",
        headers=headers,
        json=payload,
    )
    resp.raise_for_status()
    invoice = resp.json()
    logger.info(
        "Proforma invoice created: #%s (id=%s)",
        invoice.get("number"),
        invoice["id"],
    )
    return invoice


async def fire_invoice(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    invoice_id: int,
) -> None:
    """Fire (finalize) a proforma invoice, converting it to a regular invoice."""
    resp = await client.post(
        f"{base_url}/api/v3/accounts/{slug}/invoices/{invoice_id}/fire.json",
        headers=_headers(token, user_agent),
    )
    resp.raise_for_status()
    logger.info("Invoice %d fired (finalized)", invoice_id)


async def delete_invoice(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    invoice_id: int,
) -> None:
    """Delete a proforma invoice (used when user rejects approval)."""
    resp = await client.delete(
        f"{base_url}/api/v3/accounts/{slug}/invoices/{invoice_id}.json",
        headers=_headers(token, user_agent),
    )
    resp.raise_for_status()
    logger.info("Invoice %d deleted", invoice_id)
