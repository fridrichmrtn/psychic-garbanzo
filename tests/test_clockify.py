from datetime import UTC, datetime

import pytest
from invoicing.clockify import (
    ClockifySummary,
    TimeEntry,
    _parse_time_entry,
    parse_iso8601_duration,
)


def test_parse_iso8601_duration_converts_to_hours() -> None:
    assert parse_iso8601_duration("PT2H30M15S") == pytest.approx(2.5041666667)


def test_parse_iso8601_duration_invalid_value_returns_zero() -> None:
    assert parse_iso8601_duration("nope") == 0.0


def test_parse_time_entry_uses_project_name_and_rounds_duration() -> None:
    entry = _parse_time_entry(
        {
            "description": "Consulting",
            "project": {"name": "Acme"},
            "billable": True,
            "timeInterval": {
                "duration": "PT1H30M",
                "start": "2026-03-01T09:00:00Z",
                "end": "2026-03-01T10:30:00Z",
            },
        }
    )

    assert entry == TimeEntry(
        description="Consulting",
        project_name="Acme",
        duration_hours=1.5,
        start=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 10, 30, tzinfo=UTC),
        billable=True,
    )


def test_clockify_summary_model_is_unchanged() -> None:
    summary = ClockifySummary(
        entries=[],
        total_hours=0.0,
        period_start="2026-03-01",
        period_end="2026-03-31",
    )

    assert summary.model_dump() == {
        "entries": [],
        "total_hours": 0.0,
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
    }
