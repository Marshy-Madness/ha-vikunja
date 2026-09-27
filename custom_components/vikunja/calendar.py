"""A calendar of open Vikunja tasks that have dates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DUE_EVENT_LENGTH
from .coordinator import VikunjaConfigEntry, VikunjaCoordinator
from .entity import VikunjaEntity
from .models import html_to_text, parse_date


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VikunjaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VikunjaCalendar(entry.runtime_data)])


class VikunjaCalendar(VikunjaEntity, CalendarEntity):
    """Tasks with a start and end date span them; otherwise they sit at the due date.

    Calendar triggers make this the easy way to be reminded when a task comes due.
    """

    _attr_translation_key = "tasks"

    def __init__(self, coordinator: VikunjaCoordinator) -> None:
        super().__init__(coordinator, "calendar")

    def _event(self, task: dict[str, Any]) -> CalendarEvent | None:
        start = parse_date(task.get("start_date"))
        end = parse_date(task.get("end_date"))
        if not (start and end and start < end):
            if (due := parse_date(task.get("due_date"))) is None:
                return None
            start, end = due, due + DUE_EVENT_LENGTH
        project = self.coordinator.data.paths.get(task.get("project_id", 0))
        return CalendarEvent(
            start=start,
            end=end,
            summary=task.get("title") or "",
            description=html_to_text(task.get("description")) or None,
            location=project,
            uid=str(task["id"]),
        )

    def _events(self) -> list[CalendarEvent]:
        events = (self._event(t) for t in self.coordinator.data.open_tasks)
        return sorted((e for e in events if e), key=lambda e: e.start_datetime_local)

    @property
    def event(self) -> CalendarEvent | None:
        """The event in progress, else the next one."""
        now = dt_util.now()
        return next((e for e in self._events() if e.end_datetime_local > now), None)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self._events()
            if e.start_datetime_local < end_date and e.end_datetime_local > start_date
        ]
