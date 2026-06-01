"""Shared workflow helpers for the invoicing CLI."""

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from invoicing.clockify import ClockifySummary, fetch_time_entries
from invoicing.config import InvoicingSettings
from invoicing.fakturoid import (
    create_proforma_invoice,
    find_subject,
    get_oauth_token,
)


@dataclass(slots=True)
class InvoiceDraftResult:
    """Intermediate result used by create and run invoice workflows."""

    summary: ClockifySummary
    token: str
    subject: dict[str, Any]
    invoice: dict[str, Any]
    rate: float
    vat_rate: int


def require_rate(provided_rate: float | None, default_rate: float) -> float:
    """Resolve the effective hourly rate or raise when unavailable."""
    rate = provided_rate or default_rate
    if rate <= 0:
        raise ValueError("Hourly rate must be positive.")
    return rate


def build_fakturoid_url(base_url: str, slug: str, invoice_id: int) -> str:
    """Build the Fakturoid UI URL for an invoice."""
    return f"{base_url}/{slug}/invoices/{invoice_id}"


def format_total_amount(total_hours: float, rate: float) -> str:
    """Format the invoice total amount shown in Slack."""
    return f"{total_hours * rate:,.0f} CZK"


def hours_by_project(summary: ClockifySummary) -> dict[str, float]:
    """Group time entries by project name and sum hours."""
    by_project: dict[str, float] = {}
    for entry in summary.entries:
        project_name = entry.project_name or "(no project)"
        by_project[project_name] = round(
            by_project.get(project_name, 0.0) + entry.duration_hours, 2
        )
    return by_project


def summary_to_output(summary: ClockifySummary) -> dict[str, Any]:
    """Serialize a Clockify summary into the CLI JSON response shape."""
    output: dict[str, Any] = {
        "total_hours": summary.total_hours,
        "entry_count": len(summary.entries),
        "period_start": summary.period_start,
        "period_end": summary.period_end,
        "by_project": hours_by_project(summary),
        "entries": [
            {
                "description": entry.description,
                "project": entry.project_name,
                "hours": entry.duration_hours,
                "date": entry.start.strftime("%Y-%m-%d"),
                "billable": entry.billable,
            }
            for entry in summary.entries
        ],
    }
    return output


async def fetch_summary(
    client: httpx.AsyncClient,
    settings: InvoicingSettings,
    start_date: str,
    end_date: str,
) -> ClockifySummary:
    """Fetch time summary for the given period."""
    return await fetch_time_entries(
        client,
        settings.clockify_api_key,
        settings.clockify_base_url,
        start_date,
        end_date,
    )


async def create_invoice_draft(
    client: httpx.AsyncClient,
    settings: InvoicingSettings,
    summary: ClockifySummary,
    rate: float,
    lines: list[dict[str, Any]],
    due_on: str | None = None,
) -> InvoiceDraftResult:
    """Create a Fakturoid proforma invoice for the specified period.

    When ``due_on`` (a YYYY-MM-DD maturity date) is given, it is translated
    into Fakturoid's ``due`` day count relative to ``issued_on`` (Fakturoid
    computes ``due_on`` itself and treats it as read-only).
    """
    period_end = date.fromisoformat(summary.period_end)
    last_day = calendar.monthrange(period_end.year, period_end.month)[1]
    issued_date = period_end.replace(day=last_day)
    issued_on = issued_date.isoformat()
    due: int | None = None
    if due_on:
        due = (date.fromisoformat(due_on) - issued_date).days
        if due < 0:
            raise ValueError(
                f"Maturity date {due_on} is before issue date {issued_on}."
            )
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
    invoice = await create_proforma_invoice(
        client,
        settings.fakturoid_base_url,
        settings.fakturoid_slug,
        token,
        settings.fakturoid_user_agent,
        subject["id"],
        lines,
        issued_on=issued_on,
        due=due,
    )
    return InvoiceDraftResult(
        summary=summary,
        token=token,
        subject=subject,
        invoice=invoice,
        rate=rate,
        vat_rate=settings.default_vat_rate,
    )
