"""Fakturoid API client for invoice creation and management."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _headers(token: str, user_agent: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": user_agent,
        "Accept": "application/json",
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
        f"{base_url}/api/v3/oauth/token.json",
        auth=(client_id, client_secret),
        json={"grant_type": "client_credentials"},
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(
            f"Fakturoid OAuth response missing access_token: {list(data.keys())}"
        )
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
    logger.info("Found subject: %s (id=%s)", subjects[0]["name"], subjects[0]["id"])
    return subjects[0]


async def create_proforma_invoice(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    subject_id: int,
    lines: list[dict[str, Any]],
    issued_on: str | None = None,
    due: int | None = None,
) -> dict[str, Any]:
    """
    Create a proforma (draft) invoice in Fakturoid.

    The proforma has a real invoice number but is not yet a tax document.
    Call fire_invoice() after approval to convert it.

    Returns:
        Created invoice dict from Fakturoid API.
    """
    headers = {**_headers(token, user_agent), "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "subject_id": subject_id,
        "proforma": True,
        "lines": lines,
    }
    if issued_on:
        payload["issued_on"] = issued_on
    if due is not None:
        payload["due"] = due
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


async def get_invoice(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    invoice_id: int,
) -> dict[str, Any]:
    """
    Fetch a single invoice by its ID.

    Returns:
        Invoice dict.

    Raises:
        httpx.HTTPStatusError: if the invoice is not found.
    """
    resp = await client.get(
        f"{base_url}/api/v3/accounts/{slug}/invoices/{invoice_id}.json",
        headers=_headers(token, user_agent),
    )
    resp.raise_for_status()
    invoice = resp.json()
    logger.info("Found invoice: #%s (id=%s)", invoice.get("number"), invoice["id"])
    return invoice


async def search_invoices(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    query: str,
) -> dict[str, Any]:
    """
    Search for an invoice by number or other query string.

    Returns:
        First matching invoice dict.

    Raises:
        ValueError: if no invoice matches the query.
    """
    resp = await client.get(
        f"{base_url}/api/v3/accounts/{slug}/invoices/search.json",
        headers=_headers(token, user_agent),
        params={"query": query},
    )
    resp.raise_for_status()
    invoices = resp.json()
    if not invoices:
        raise ValueError(f"No Fakturoid invoice found matching '{query}'")
    logger.info(
        "Found invoice: #%s (id=%s)", invoices[0].get("number"), invoices[0]["id"]
    )
    return invoices[0]


async def get_subject(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    subject_id: int,
) -> dict[str, Any]:
    """
    Fetch a subject (client) by ID.

    Returns:
        Subject dict from Fakturoid API.
    """
    resp = await client.get(
        f"{base_url}/api/v3/accounts/{slug}/subjects/{subject_id}.json",
        headers=_headers(token, user_agent),
    )
    resp.raise_for_status()
    subject = resp.json()
    logger.info("Fetched subject: %s (id=%s)", subject["name"], subject["id"])
    return subject


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


async def download_pdf(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
    token: str,
    user_agent: str,
    invoice_id: int,
) -> bytes:
    """Download the PDF for an invoice.

    Returns:
        Raw PDF bytes.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": user_agent,
        "Accept": "application/pdf",
    }
    resp = await client.get(
        f"{base_url}/api/v3/accounts/{slug}/invoices/{invoice_id}/download.pdf",
        headers=headers,
    )
    resp.raise_for_status()
    logger.info(
        "Downloaded PDF for invoice %d (%d bytes)", invoice_id, len(resp.content)
    )
    return resp.content
