import argparse
import json
import os
from argparse import Namespace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from invoicing.__main__ import (
    _positive_float,
    _valid_date,
    build_invoice_lines,
    cmd_create,
    cmd_fetch,
    cmd_fire,
    cmd_notify,
    cmd_run,
    format_preview,
)
from invoicing.clockify import ClockifySummary, TimeEntry
from invoicing.workflows import (
    InvoiceDraftResult,
    build_fakturoid_url,
    format_total_amount,
    require_rate,
    summary_to_output,
)

# Test-only placeholder tokens — never use real credentials
_TEST_SLACK_TOKEN = os.environ.get("TEST_SLACK_BOT_TOKEN", "xoxb-000-000-placeholder")
_TEST_SLACK_CHANNEL = os.environ.get("TEST_SLACK_CHANNEL", "C000test")


@pytest.fixture
def settings() -> SimpleNamespace:
    return SimpleNamespace(
        clockify_api_key="test-clockify-key",
        clockify_base_url="https://clockify.example",
        fakturoid_client_id="test-client-id",
        fakturoid_client_secret="test-client-secret",
        fakturoid_slug="acme",
        fakturoid_subject_name="Acme Corp",
        fakturoid_user_agent="TestBot",
        fakturoid_base_url="https://fakturoid.example",
        slack_bot_token=_TEST_SLACK_TOKEN,
        slack_channel=_TEST_SLACK_CHANNEL,
        default_hourly_rate=100.0,
        default_vat_rate=21,
    )


@pytest.fixture
def summary() -> ClockifySummary:
    return ClockifySummary(
        entries=[
            TimeEntry(
                description="Kickoff",
                project_name="Project A",
                duration_hours=1.25,
                start=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
                end=datetime(2026, 3, 1, 10, 15, tzinfo=UTC),
                billable=True,
            ),
            TimeEntry(
                description="Admin",
                project_name=None,
                duration_hours=0.75,
                start=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
                end=datetime(2026, 3, 2, 9, 45, tzinfo=UTC),
                billable=False,
            ),
        ],
        total_hours=2.0,
        period_start="2026-03-01",
        period_end="2026-03-31",
    )


def test_build_invoice_lines_output_shape() -> None:
    assert build_invoice_lines(
        {"Project A": 1.25, "Project B": 0.75},
        100.0,
        21,
        "2026-03-01",
        "2026-03-31",
    ) == [
        {
            "name": "Project A (2026-03-01 — 2026-03-31)",
            "quantity": 1.25,
            "unit_name": "hrs",
            "unit_price": 100.0,
            "vat_rate": 21,
        },
        {
            "name": "Project B (2026-03-01 — 2026-03-31)",
            "quantity": 0.75,
            "unit_name": "hrs",
            "unit_price": 100.0,
            "vat_rate": 21,
        },
    ]


def test_format_preview_contains_expected_totals() -> None:
    preview = format_preview("Acme", "2026-03-01 to 2026-03-31", 2.0, 100.0, 21)

    assert "INVOICE PREVIEW" in preview
    assert "Acme" in preview
    assert "200 CZK" in preview
    assert "242 CZK" in preview


def test_require_rate_uses_provided_value() -> None:
    assert require_rate(200.0, 100.0) == 200.0


def test_require_rate_raises_for_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="Hourly rate must be positive."):
        require_rate(None, 0.0)


def test_summary_to_output_preserves_current_json_shape(
    summary: ClockifySummary,
) -> None:
    assert summary_to_output(summary) == {
        "total_hours": 2.0,
        "entry_count": 2,
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
        "by_project": {
            "Project A": 1.25,
            "(no project)": 0.75,
        },
        "entries": [
            {
                "description": "Kickoff",
                "project": "Project A",
                "hours": 1.25,
                "date": "2026-03-01",
                "billable": True,
            },
            {
                "description": "Admin",
                "project": None,
                "hours": 0.75,
                "date": "2026-03-02",
                "billable": False,
            },
        ],
    }


def test_build_fakturoid_url() -> None:
    assert (
        build_fakturoid_url("https://fakturoid.example", "acme", 42)
        == "https://fakturoid.example/acme/invoices/42"
    )


def test_format_total_amount() -> None:
    assert format_total_amount(2.0, 100.0) == "200 CZK"


@pytest.mark.asyncio
async def test_cmd_fetch_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    summary: ClockifySummary,
) -> None:
    monkeypatch.setattr(
        "invoicing.__main__.fetch_summary", AsyncMock(return_value=summary)
    )

    await cmd_fetch(Namespace(start="2026-03-01", end="2026-03-31"), settings)

    assert json.loads(capsys.readouterr().out) == summary_to_output(summary)


@pytest.mark.asyncio
async def test_cmd_create_prints_invoice_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
    summary: ClockifySummary,
) -> None:
    draft = InvoiceDraftResult(
        summary=summary,
        token="token",
        subject={"id": 7, "name": "Acme Corp"},
        invoice={"id": 42, "number": "2026001", "subtotal": "200", "total": "242"},
        rate=100.0,
        vat_rate=21,
    )
    monkeypatch.setattr(
        "invoicing.__main__.fetch_summary", AsyncMock(return_value=summary)
    )
    monkeypatch.setattr(
        "invoicing.__main__.create_invoice_draft", AsyncMock(return_value=draft)
    )

    await cmd_create(
        Namespace(start="2026-03-01", end="2026-03-31", rate=100.0),
        settings,
    )

    assert json.loads(capsys.readouterr().out) == {
        "invoice_id": 42,
        "invoice_number": "2026001",
        "subject_name": "Acme Corp",
        "total_hours": 2.0,
        "rate": 100.0,
        "vat_rate": 21,
        "subtotal": "200",
        "total": "242",
        "issued_on": None,
        "due_on": None,
        "status": "proforma",
        "fakturoid_url": "https://fakturoid.example/acme/invoices/42",
    }


@pytest.mark.asyncio
async def test_cmd_create_exits_when_no_hours(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    draft = InvoiceDraftResult(
        summary=ClockifySummary(
            entries=[],
            total_hours=0.0,
            period_start="2026-03-01",
            period_end="2026-03-31",
        ),
        token="token",
        subject={"id": 7, "name": "Acme Corp"},
        invoice={"id": 42},
        rate=100.0,
        vat_rate=21,
    )
    monkeypatch.setattr(
        "invoicing.__main__.fetch_summary", AsyncMock(return_value=draft.summary)
    )
    monkeypatch.setattr(
        "invoicing.__main__.create_invoice_draft", AsyncMock(return_value=draft)
    )

    with pytest.raises(SystemExit) as exc:
        await cmd_create(
            Namespace(start="2026-03-01", end="2026-03-31", rate=100.0),
            settings,
        )

    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"error": "No billable hours found"}


@pytest.mark.asyncio
async def test_cmd_notify_manual_args(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    send_mock = AsyncMock(return_value={"message_sent": True, "pdf_uploaded": False})
    monkeypatch.setattr("invoicing.__main__.send_invoice_notification", send_mock)

    await cmd_notify(
        Namespace(
            invoice_id=None,
            invoice_number="2026001",
            amount="200 CZK",
            hours=2.0,
            period="2026-03-01 - 2026-03-31",
            client="Acme Corp",
        ),
        settings,
    )

    send_mock.assert_awaited_once()
    call_kwargs = send_mock.call_args
    assert call_kwargs[1]["invoice_number"] == "2026001"
    assert call_kwargs[1]["pdf_bytes"] is None
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "notified"
    assert out["pdf_uploaded"] is False
    assert "message_ts" in out
    assert "channel_id" in out


@pytest.mark.asyncio
async def test_cmd_notify_exits_without_bot_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    settings.slack_bot_token = ""
    with pytest.raises(SystemExit) as exc:
        await cmd_notify(
            Namespace(
                invoice_id=None,
                invoice_number="X",
                amount="0",
                hours=0,
                period="",
                client="",
            ),
            settings,
        )
    assert exc.value.code == 1
    assert "SLACK_BOT_TOKEN" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_cmd_notify_exits_without_channel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    settings.slack_channel = ""
    with pytest.raises(SystemExit) as exc:
        await cmd_notify(
            Namespace(
                invoice_id=None,
                invoice_number="X",
                amount="0",
                hours=0,
                period="",
                client="",
            ),
            settings,
        )
    assert exc.value.code == 1
    assert "SLACK_CHANNEL" in capsys.readouterr().err


# -- invoice-id lookup path tests --

_FAKE_INVOICE = {
    "id": 42,
    "number": "2026002",
    "total": "400.0",
    "issued_on": "2026-03-01",
    "subject_id": 7,
    "lines": [
        {"quantity": "1.5", "name": "Dev"},
        {"quantity": "2.5", "name": "Review"},
    ],
}
_FAKE_SUBJECT = {"name": "Acme Corp"}


def _patch_fakturoid(monkeypatch, *, pdf_side_effect=None):
    """Patch all Fakturoid helpers used by the invoice-id lookup path."""
    monkeypatch.setattr(
        "invoicing.__main__.get_oauth_token", AsyncMock(return_value="tok")
    )
    monkeypatch.setattr(
        "invoicing.__main__.get_invoice", AsyncMock(return_value=_FAKE_INVOICE)
    )
    monkeypatch.setattr(
        "invoicing.__main__.get_subject", AsyncMock(return_value=_FAKE_SUBJECT)
    )
    if pdf_side_effect:
        monkeypatch.setattr(
            "invoicing.__main__.download_pdf",
            AsyncMock(side_effect=pdf_side_effect),
        )
    else:
        monkeypatch.setattr(
            "invoicing.__main__.download_pdf", AsyncMock(return_value=b"%PDF-fake")
        )
    send_mock = AsyncMock(return_value={"message_sent": True, "pdf_uploaded": True})
    monkeypatch.setattr("invoicing.__main__.send_invoice_notification", send_mock)
    return send_mock


@pytest.mark.asyncio
async def test_cmd_notify_invoice_id_lookup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    """Invoice-id path sums hours across multiple lines and passes PDF bytes."""
    send_mock = _patch_fakturoid(monkeypatch)

    await cmd_notify(
        Namespace(
            invoice_id=42,
            invoice_number=None,
            amount=None,
            hours=None,
            period=None,
            client=None,
        ),
        settings,
    )

    send_mock.assert_awaited_once()
    kw = send_mock.call_args[1]
    assert kw["total_hours"] == 4.0  # 1.5 + 2.5
    assert kw["pdf_bytes"] == b"%PDF-fake"
    assert kw["invoice_number"] == "2026002"
    assert kw["client_name"] == "Acme Corp"


@pytest.mark.asyncio
async def test_cmd_notify_invoice_id_pdf_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    """PDF download failure (ConnectError) is best-effort — notification still sent."""
    send_mock = _patch_fakturoid(
        monkeypatch,
        pdf_side_effect=httpx.ConnectError("connection refused"),
    )

    await cmd_notify(
        Namespace(
            invoice_id=42,
            invoice_number=None,
            amount=None,
            hours=None,
            period=None,
            client=None,
        ),
        settings,
    )

    send_mock.assert_awaited_once()
    kw = send_mock.call_args[1]
    assert kw["pdf_bytes"] is None
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "notified"


# -- cmd_fire idempotent tests --


@pytest.mark.asyncio
async def test_cmd_fire_already_converted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    """If Fakturoid auto-converted proforma, fire returns already_fired."""
    monkeypatch.setattr(
        "invoicing.__main__.get_oauth_token", AsyncMock(return_value="tok")
    )
    monkeypatch.setattr(
        "invoicing.__main__.get_invoice",
        AsyncMock(return_value={"document_type": "invoice", "status": "open"}),
    )
    fire_mock = AsyncMock()
    monkeypatch.setattr("invoicing.__main__.fire_invoice", fire_mock)

    await cmd_fire(Namespace(invoice_id=42), settings)

    fire_mock.assert_not_awaited()
    out = json.loads(capsys.readouterr().out)
    assert out == {"invoice_id": 42, "status": "already_fired"}


@pytest.mark.asyncio
async def test_cmd_fire_proforma(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    """Normal proforma gets fired."""
    monkeypatch.setattr(
        "invoicing.__main__.get_oauth_token", AsyncMock(return_value="tok")
    )
    monkeypatch.setattr(
        "invoicing.__main__.get_invoice",
        AsyncMock(return_value={"document_type": "proforma", "status": "open"}),
    )
    fire_mock = AsyncMock()
    monkeypatch.setattr("invoicing.__main__.fire_invoice", fire_mock)

    await cmd_fire(Namespace(invoice_id=42), settings)

    fire_mock.assert_awaited_once()
    out = json.loads(capsys.readouterr().out)
    assert out == {"invoice_id": 42, "status": "fired"}


# -- cmd_notify output includes ts and channel_id --


@pytest.mark.asyncio
async def test_cmd_notify_output_includes_ts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    """Notify output includes message_ts and channel_id from Slack response."""
    send_mock = AsyncMock(
        return_value={
            "message_sent": True,
            "pdf_uploaded": False,
            "message_ts": "1234567890.123456",
            "channel_id": "C000test",
        }
    )
    monkeypatch.setattr("invoicing.__main__.send_invoice_notification", send_mock)

    await cmd_notify(
        Namespace(
            invoice_id=None,
            invoice_number="2026001",
            amount="200 CZK",
            hours=2.0,
            period="2026-03-01 - 2026-03-31",
            client="Acme Corp",
        ),
        settings,
    )

    out = json.loads(capsys.readouterr().out)
    assert out["message_ts"] == "1234567890.123456"
    assert out["channel_id"] == "C000test"


# -- resolve_channel_id tests --


@pytest.mark.asyncio
async def test_resolve_channel_id_passthrough() -> None:
    """Channel IDs starting with C/G are returned as-is."""
    from invoicing.slack import resolve_channel_id

    result = await resolve_channel_id(AsyncMock(), "tok", "C0A9SFHRJ7J")
    assert result == "C0A9SFHRJ7J"


@pytest.mark.asyncio
async def test_resolve_channel_id_by_name() -> None:
    """Channel names are resolved via conversations.list."""
    from invoicing.slack import resolve_channel_id

    client = AsyncMock()
    client.get = AsyncMock(
        return_value=SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "ok": True,
                "channels": [
                    {"id": "C111", "name": "general"},
                    {"id": "C222", "name": "invoicing"},
                ],
            },
        )
    )

    result = await resolve_channel_id(client, "tok", "invoicing")
    assert result == "C222"


@pytest.mark.asyncio
async def test_resolve_channel_id_not_found() -> None:
    """Unknown channel name raises RuntimeError."""
    from invoicing.slack import resolve_channel_id

    client = AsyncMock()
    client.get = AsyncMock(
        return_value=SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"ok": True, "channels": []},
        )
    )

    with pytest.raises(RuntimeError, match="Slack channel not found"):
        await resolve_channel_id(client, "tok", "nonexistent")


# -- cmd_run E2E tests --


@pytest.fixture
def _patch_run_pipeline(monkeypatch, summary):
    """Patch all external calls used by cmd_run's full pipeline."""
    draft = InvoiceDraftResult(
        summary=summary,
        token="tok",
        subject={"id": 7, "name": "Acme Corp"},
        invoice={"id": 42, "number": "2026001"},
        rate=100.0,
        vat_rate=21,
    )
    monkeypatch.setattr(
        "invoicing.__main__.fetch_summary", AsyncMock(return_value=summary)
    )
    monkeypatch.setattr(
        "invoicing.__main__.create_invoice_draft", AsyncMock(return_value=draft)
    )
    fire_mock = AsyncMock()
    monkeypatch.setattr("invoicing.__main__.fire_invoice", fire_mock)
    monkeypatch.setattr(
        "invoicing.__main__.download_pdf", AsyncMock(return_value=b"%PDF-fake")
    )
    send_mock = AsyncMock(
        return_value={"message_sent": True, "pdf_uploaded": True, "ts": "123"}
    )
    monkeypatch.setattr("invoicing.__main__.send_invoice_notification", send_mock)
    return {"fire": fire_mock, "send": send_mock, "draft": draft}


@pytest.mark.asyncio
async def test_cmd_run_approved_fires_and_notifies(
    monkeypatch,
    capsys,
    settings,
    summary,
    _patch_run_pipeline,
) -> None:
    """Full pipeline: approval → fire → notify."""
    monkeypatch.setattr("invoicing.__main__.prompt_approval", lambda: True)
    mocks = _patch_run_pipeline

    await cmd_run(
        Namespace(start="2026-03-01", end="2026-03-31", rate=100.0, dry_run=False),
        settings,
    )

    mocks["fire"].assert_awaited_once()
    mocks["send"].assert_awaited_once()
    output = capsys.readouterr().out
    assert "Done." in output


@pytest.mark.asyncio
async def test_cmd_run_rejected_deletes_proforma(
    monkeypatch,
    capsys,
    settings,
    summary,
    _patch_run_pipeline,
) -> None:
    """Rejected approval → proforma deleted, no fire."""
    monkeypatch.setattr("invoicing.__main__.prompt_approval", lambda: False)
    delete_mock = AsyncMock()
    monkeypatch.setattr("invoicing.__main__.delete_invoice", delete_mock)
    mocks = _patch_run_pipeline

    with pytest.raises(SystemExit) as exc:
        await cmd_run(
            Namespace(start="2026-03-01", end="2026-03-31", rate=100.0, dry_run=False),
            settings,
        )

    assert exc.value.code == 0
    mocks["fire"].assert_not_awaited()
    delete_mock.assert_awaited_once()
    assert "Proforma deleted" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cmd_run_dry_run_exits_without_creating(
    monkeypatch,
    capsys,
    settings,
    summary,
) -> None:
    """Dry run prints preview and exits without creating."""
    monkeypatch.setattr(
        "invoicing.__main__.fetch_summary", AsyncMock(return_value=summary)
    )
    create_mock = AsyncMock()
    monkeypatch.setattr("invoicing.__main__.create_invoice_draft", create_mock)

    with pytest.raises(SystemExit) as exc:
        await cmd_run(
            Namespace(start="2026-03-01", end="2026-03-31", rate=100.0, dry_run=True),
            settings,
        )

    assert exc.value.code == 0
    create_mock.assert_not_awaited()
    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert "INVOICE PREVIEW" in output


# ---------------------------------------------------------------------------
# _valid_date / _positive_float validators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["2026-03-01", "2000-01-01", "2099-12-31"])
def test_valid_date_accepts_canonical(value: str) -> None:
    assert _valid_date(value) == value


@pytest.mark.parametrize("value", ["2026-3-1", "not-a-date", "2026/03/01", ""])
def test_valid_date_rejects_bad_input(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="Expected YYYY-MM-DD"):
        _valid_date(value)


@pytest.mark.parametrize("value,expected", [("100", 100.0), ("0.5", 0.5), ("1", 1.0)])
def test_positive_float_accepts_valid(value: str, expected: float) -> None:
    assert _positive_float(value) == expected


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_positive_float_rejects_invalid(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="positive finite number"):
        _positive_float(value)


def test_positive_float_rejects_non_numeric() -> None:
    with pytest.raises(ValueError):
        _positive_float("abc")
