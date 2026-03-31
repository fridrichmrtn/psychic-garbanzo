import json
from argparse import Namespace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from invoicing.__main__ import (
    build_invoice_lines,
    cmd_create,
    cmd_fetch,
    cmd_notify,
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


@pytest.fixture
def settings() -> SimpleNamespace:
    return SimpleNamespace(
        clockify_api_key="clockify-key",
        clockify_base_url="https://clockify.example",
        fakturoid_client_id="client-id",
        fakturoid_client_secret="client-secret",
        fakturoid_slug="acme",
        fakturoid_subject_name="Acme Corp",
        fakturoid_user_agent="Bot",
        fakturoid_base_url="https://fakturoid.example",
        slack_webhook_url="https://slack.example",
        default_hourly_rate=1500.0,
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
                start=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
                end=datetime(2026, 3, 1, 10, 15, tzinfo=timezone.utc),
                billable=True,
            ),
            TimeEntry(
                description="Admin",
                project_name=None,
                duration_hours=0.75,
                start=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
                end=datetime(2026, 3, 2, 9, 45, tzinfo=timezone.utc),
                billable=False,
            ),
        ],
        total_hours=2.0,
        period_start="2026-03-01",
        period_end="2026-03-31",
    )


def test_build_invoice_lines_output_shape() -> None:
    assert build_invoice_lines(2.0, 1500.0, 21, "2026-03-01", "2026-03-31") == [
        {
            "name": "Consulting services (2026-03-01 — 2026-03-31)",
            "quantity": 2.0,
            "unit_name": "hrs",
            "unit_price": 1500.0,
            "vat_rate": 21,
        }
    ]


def test_format_preview_contains_expected_totals() -> None:
    preview = format_preview("Acme", "2026-03-01 to 2026-03-31", 2.0, 1500.0, 21)

    assert "INVOICE PREVIEW" in preview
    assert "Acme" in preview
    assert "3,000 CZK" in preview
    assert "3,630 CZK" in preview


def test_require_rate_uses_provided_value() -> None:
    assert require_rate(2000.0, 1500.0) == 2000.0


def test_require_rate_raises_for_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="Hourly rate must be positive."):
        require_rate(None, 0.0)


def test_summary_to_output_preserves_current_json_shape(summary: ClockifySummary) -> None:
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
        == "https://fakturoid.example/i/acme/42"
    )


def test_format_total_amount() -> None:
    assert format_total_amount(2.0, 1500.0) == "3,000 CZK"


@pytest.mark.asyncio
async def test_cmd_fetch_prints_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], settings: SimpleNamespace, summary: ClockifySummary) -> None:
    monkeypatch.setattr("invoicing.__main__.fetch_summary", AsyncMock(return_value=summary))

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
        invoice={"id": 42, "number": "2026001", "subtotal": "3000", "total": "3630"},
        rate=1500.0,
        vat_rate=21,
    )
    monkeypatch.setattr("invoicing.__main__.fetch_summary", AsyncMock(return_value=summary))
    monkeypatch.setattr("invoicing.__main__.create_invoice_draft", AsyncMock(return_value=draft))

    await cmd_create(
        Namespace(start="2026-03-01", end="2026-03-31", rate=1500.0),
        settings,
    )

    assert json.loads(capsys.readouterr().out) == {
        "invoice_id": 42,
        "invoice_number": "2026001",
        "subject_name": "Acme Corp",
        "total_hours": 2.0,
        "rate": 1500.0,
        "vat_rate": 21,
        "subtotal": "3000",
        "total": "3630",
        "status": "proforma",
        "fakturoid_url": "https://fakturoid.example/i/acme/42",
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
        rate=1500.0,
        vat_rate=21,
    )
    monkeypatch.setattr("invoicing.__main__.fetch_summary", AsyncMock(return_value=draft.summary))
    monkeypatch.setattr("invoicing.__main__.create_invoice_draft", AsyncMock(return_value=draft))

    with pytest.raises(SystemExit) as exc:
        await cmd_create(
            Namespace(start="2026-03-01", end="2026-03-31", rate=1500.0),
            settings,
        )

    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"error": "No billable hours found"}


@pytest.mark.asyncio
async def test_cmd_notify_uses_slack_helper(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: SimpleNamespace,
) -> None:
    send_invoice_notification = AsyncMock()
    monkeypatch.setattr("invoicing.__main__.send_invoice_notification", send_invoice_notification)

    await cmd_notify(
        Namespace(
            invoice_number="2026001",
            amount="3,000 CZK",
            hours=2.0,
            period="2026-03-01 - 2026-03-31",
            client="Acme Corp",
        ),
        settings,
    )

    send_invoice_notification.assert_awaited_once()
    assert json.loads(capsys.readouterr().out) == {"status": "notified"}
