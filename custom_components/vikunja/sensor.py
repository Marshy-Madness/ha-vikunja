"""Task count and next-due sensors for Vikunja."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import VikunjaConfigEntry, VikunjaCoordinator
from .entity import VikunjaEntity
from .models import parse_date

# Keep attributes well under the recorder's 16 KiB limit.
MAX_LISTED_TASKS = 20

# Sorts undated tasks last.
NEVER = datetime.max.replace(tzinfo=dt_util.UTC)


def _due(task: dict[str, Any]) -> datetime | None:
    return parse_date(task.get("due_date"))


def _overdue(task: dict[str, Any]) -> bool:
    return (due := _due(task)) is not None and due < dt_util.now()


def _due_today(task: dict[str, Any]) -> bool:
    return (due := _due(task)) is not None and due.date() == dt_util.now().date()


def _due_this_week(task: dict[str, Any]) -> bool:
    now = dt_util.now()
    return (due := _due(task)) is not None and now <= due < now + timedelta(days=7)


@dataclass(frozen=True, kw_only=True)
class VikunjaCountDescription(SensorEntityDescription):
    """Number of open tasks matching a predicate, which are listed as attributes."""

    predicate: Callable[[dict[str, Any]], bool]
    list_tasks: bool = True


COUNT_SENSORS = (
    VikunjaCountDescription(
        key="open_tasks",
        translation_key="open_tasks",
        predicate=lambda task: True,
        list_tasks=False,
    ),
    VikunjaCountDescription(
        key="overdue_tasks",
        translation_key="overdue_tasks",
        predicate=_overdue,
    ),
    VikunjaCountDescription(
        key="due_today",
        translation_key="due_today",
        predicate=_due_today,
    ),
    VikunjaCountDescription(
        key="due_this_week",
        translation_key="due_this_week",
        predicate=_due_this_week,
    ),
    VikunjaCountDescription(
        key="high_priority_tasks",
        translation_key="high_priority_tasks",
        # Vikunja's priorities: 3 high, 4 urgent, 5 do now.
        predicate=lambda task: task.get("priority", 0) >= 3,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VikunjaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(VikunjaCountSensor(coordinator, d) for d in COUNT_SENSORS),
            VikunjaNextDueSensor(coordinator),
        ]
    )


class VikunjaCountSensor(VikunjaEntity, SensorEntity):
    """How many open tasks match; the soonest-due ones are listed."""

    entity_description: VikunjaCountDescription
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "tasks"

    def __init__(
        self, coordinator: VikunjaCoordinator, description: VikunjaCountDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def _tasks(self) -> list[dict[str, Any]]:
        return [
            t for t in self.coordinator.data.open_tasks if self.entity_description.predicate(t)
        ]

    @property
    def native_value(self) -> int:
        return len(self._tasks)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tasks = self._tasks
        paths = self.coordinator.data.paths
        attrs: dict[str, Any] = {
            "by_project": dict(
                Counter(paths.get(t["project_id"], "?") for t in tasks).most_common()
            )
        }
        if self.entity_description.list_tasks:
            tasks.sort(key=lambda t: (_due(t) or NEVER, -t.get("priority", 0)))
            attrs["tasks"] = [self.coordinator.public(t) for t in tasks[:MAX_LISTED_TASKS]]
        return attrs


class VikunjaNextDueSensor(VikunjaEntity, SensorEntity):
    """When the next open task is due, with that task as attributes."""

    _attr_translation_key = "next_due"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: VikunjaCoordinator) -> None:
        super().__init__(coordinator, "next_due")

    @property
    def _task(self) -> dict[str, Any] | None:
        now = dt_util.now()
        upcoming = [
            t for t in self.coordinator.data.open_tasks if (d := _due(t)) and d >= now
        ]
        return min(upcoming, key=_due, default=None)  # type: ignore[arg-type]

    @property
    def native_value(self) -> datetime | None:
        return _due(task) if (task := self._task) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.coordinator.public(task) if (task := self._task) else None
