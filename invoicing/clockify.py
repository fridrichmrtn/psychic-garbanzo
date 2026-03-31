"""Clockify API client for fetching time tracking entries."""

import logging
import re
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TimeEntry(BaseModel):
    """A single parsed time entry from Clockify."""

    description: str
    project_name: str | None
    duration_hours: float
    start: datetime
    end: datetime
    billable: bool


class ClockifySummary(BaseModel):
    """Aggregated time tracking data for an invoice period."""

    entries: list[TimeEntry]
    total_hours: float
    period_start: str
    period_end: str


def parse_iso8601_duration(duration: str) -> float:
    """Convert ISO 8601 duration (e.g. PT2H30M15S) to decimal hours."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours + minutes / 60 + seconds / 3600


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key}


async def _get_user_context(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
) -> tuple[str, str]:
    """Fetch the current user and default workspace identifiers."""
    resp = await client.get(f"{base_url}/user", headers=headers)
    resp.raise_for_status()
    user_data = resp.json()
    return user_data["id"], user_data["defaultWorkspace"]


async def _fetch_raw_time_entries(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    workspace_id: str,
    user_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Fetch all paginated raw time entries for a period."""
    all_raw: list[dict[str, Any]] = []
    page = 1
    while True:
        resp = await client.get(
            f"{base_url}/workspaces/{workspace_id}/user/{user_id}/time-entries",
            headers=headers,
            params={
                "start": f"{start_date}T00:00:00Z",
                "end": f"{end_date}T23:59:59Z",
                "hydrated": "true",
                "page-size": "200",
                "page": str(page),
            },
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_raw.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return all_raw


def _parse_time_entry(raw: dict[str, Any]) -> TimeEntry:
    """Convert a Clockify API entry into the local model."""
    interval = raw.get("timeInterval", {})
    duration = parse_iso8601_duration(interval.get("duration", "PT0S"))
    project = raw.get("project")
    return TimeEntry(
        description=raw.get("description", ""),
        project_name=project.get("name") if project else None,
        duration_hours=round(duration, 2),
        start=datetime.fromisoformat(interval["start"].replace("Z", "+00:00")),
        end=datetime.fromisoformat(interval["end"].replace("Z", "+00:00")),
        billable=raw.get("billable", False),
    )


async def fetch_time_entries(
    client: httpx.AsyncClient,
    api_key: str,
    base_url: str,
    start_date: str,
    end_date: str,
) -> ClockifySummary:
    """
    Fetch time entries from Clockify for the given date range.

    Args:
        client: httpx async client instance.
        api_key: Clockify API key.
        base_url: Clockify API base URL.
        start_date: ISO date (YYYY-MM-DD) inclusive start.
        end_date: ISO date (YYYY-MM-DD) inclusive end.

    Returns:
        ClockifySummary with parsed entries and total hours.
    """
    headers = _headers(api_key)
    user_id, workspace_id = await _get_user_context(client, base_url, headers)
    all_raw = await _fetch_raw_time_entries(
        client,
        base_url,
        headers,
        workspace_id,
        user_id,
        start_date,
        end_date,
    )
    entries = [_parse_time_entry(raw) for raw in all_raw]

    total = round(sum(e.duration_hours for e in entries), 2)
    logger.info("Fetched %d entries totalling %.2f hours", len(entries), total)

    return ClockifySummary(
        entries=entries,
        total_hours=total,
        period_start=start_date,
        period_end=end_date,
    )
