"""Tests for the Fakturoid API client module."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from invoicing.fakturoid import (
    create_proforma_invoice,
    delete_invoice,
    download_pdf,
    find_subject,
    fire_invoice,
    get_invoice,
    get_oauth_token,
    get_subject,
    search_invoices,
)


def _mock_response(json_data=None, status_code=200, content=b""):
    """Build a fake httpx.Response-like object."""
    resp = SimpleNamespace(
        status_code=status_code,
        json=lambda: json_data,
        content=content,
        raise_for_status=lambda: None,
    )
    return resp


def _mock_client(**method_returns) -> AsyncMock:
    """Build a mock httpx.AsyncClient with async methods returning given values."""
    client = AsyncMock(spec=httpx.AsyncClient)
    for method, return_value in method_returns.items():
        getattr(client, method).return_value = return_value
    return client


# -- get_oauth_token --


@pytest.mark.asyncio
async def test_get_oauth_token_returns_token() -> None:
    client = _mock_client(post=_mock_response({"access_token": "tok-123"}))

    token = await get_oauth_token(
        client, "https://fakturoid.example", "client-id", "client-secret"
    )

    assert token == "tok-123"
    client.post.assert_awaited_once()
    call_kwargs = client.post.call_args
    assert "oauth/token.json" in call_kwargs.args[0]


@pytest.mark.asyncio
async def test_get_oauth_token_missing_token_raises() -> None:
    client = _mock_client(post=_mock_response({"error": "invalid_client"}))

    with pytest.raises(RuntimeError, match="missing access_token"):
        await get_oauth_token(
            client, "https://fakturoid.example", "client-id", "client-secret"
        )


@pytest.mark.asyncio
async def test_get_oauth_token_http_error_propagates() -> None:
    resp = SimpleNamespace(
        raise_for_status=lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError(
                "401",
                request=httpx.Request("POST", "https://x"),
                response=httpx.Response(401),
            )
        ),
    )
    client = _mock_client(post=resp)

    with pytest.raises(httpx.HTTPStatusError):
        await get_oauth_token(
            client, "https://fakturoid.example", "client-id", "client-secret"
        )


# -- find_subject --


@pytest.mark.asyncio
async def test_find_subject_returns_first_match() -> None:
    subjects = [{"id": 7, "name": "Acme Corp"}, {"id": 8, "name": "Acme Inc"}]
    client = _mock_client(get=_mock_response(subjects))

    result = await find_subject(
        client, "https://fakturoid.example", "slug", "tok", "agent", "Acme"
    )

    assert result == {"id": 7, "name": "Acme Corp"}


@pytest.mark.asyncio
async def test_find_subject_no_match_raises() -> None:
    client = _mock_client(get=_mock_response([]))

    with pytest.raises(ValueError, match="No Fakturoid subject found"):
        await find_subject(
            client, "https://fakturoid.example", "slug", "tok", "agent", "NonExistent"
        )


# -- create_proforma_invoice --


@pytest.mark.asyncio
async def test_create_proforma_invoice_returns_invoice() -> None:
    invoice = {"id": 42, "number": "2026001", "total": "200"}
    client = _mock_client(post=_mock_response(invoice))

    result = await create_proforma_invoice(
        client,
        "https://fakturoid.example",
        "slug",
        "tok",
        "agent",
        subject_id=7,
        lines=[{"name": "Work", "quantity": 2, "unit_price": 100}],
    )

    assert result["id"] == 42
    call_kwargs = client.post.call_args
    assert call_kwargs.kwargs["json"]["proforma"] is True
    assert call_kwargs.kwargs["json"]["subject_id"] == 7


# -- fire_invoice --


@pytest.mark.asyncio
async def test_fire_invoice_posts_to_fire_endpoint() -> None:
    client = _mock_client(post=_mock_response(None))

    await fire_invoice(client, "https://fakturoid.example", "slug", "tok", "agent", 42)

    client.post.assert_awaited_once()
    assert "42/fire.json" in client.post.call_args.args[0]


# -- get_invoice --


@pytest.mark.asyncio
async def test_get_invoice_returns_invoice_dict() -> None:
    invoice = {"id": 42, "number": "2026001", "document_type": "proforma"}
    client = _mock_client(get=_mock_response(invoice))

    result = await get_invoice(
        client, "https://fakturoid.example", "slug", "tok", "agent", 42
    )

    assert result["id"] == 42
    assert result["document_type"] == "proforma"


# -- search_invoices --


@pytest.mark.asyncio
async def test_search_invoices_returns_first_match() -> None:
    invoices = [{"id": 42, "number": "2026001"}, {"id": 43, "number": "2026002"}]
    client = _mock_client(get=_mock_response(invoices))

    result = await search_invoices(
        client, "https://fakturoid.example", "slug", "tok", "agent", "2026001"
    )

    assert result["id"] == 42


@pytest.mark.asyncio
async def test_search_invoices_no_match_raises() -> None:
    client = _mock_client(get=_mock_response([]))

    with pytest.raises(ValueError, match="No Fakturoid invoice found"):
        await search_invoices(
            client, "https://fakturoid.example", "slug", "tok", "agent", "NOPE"
        )


# -- get_subject --


@pytest.mark.asyncio
async def test_get_subject_returns_subject_dict() -> None:
    subject = {"id": 7, "name": "Acme Corp"}
    client = _mock_client(get=_mock_response(subject))

    result = await get_subject(
        client, "https://fakturoid.example", "slug", "tok", "agent", 7
    )

    assert result == {"id": 7, "name": "Acme Corp"}


# -- delete_invoice --


@pytest.mark.asyncio
async def test_delete_invoice_calls_delete_endpoint() -> None:
    client = _mock_client(delete=_mock_response(None))

    await delete_invoice(
        client, "https://fakturoid.example", "slug", "tok", "agent", 42
    )

    client.delete.assert_awaited_once()
    assert "42.json" in client.delete.call_args.args[0]


# -- download_pdf --


@pytest.mark.asyncio
async def test_download_pdf_returns_bytes() -> None:
    pdf_content = b"%PDF-1.4 fake content"
    client = _mock_client(get=_mock_response(content=pdf_content))

    result = await download_pdf(
        client, "https://fakturoid.example", "slug", "tok", "agent", 42
    )

    assert result == pdf_content
    assert "download.pdf" in client.get.call_args.args[0]
