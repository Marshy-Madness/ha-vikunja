"""A to-do list per Vikunja project."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, ServiceResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import VikunjaApiError
from .coordinator import VikunjaConfigEntry, VikunjaCoordinator
from .entity import VikunjaEntity
from .models import format_date, html_to_text, parse_date, text_to_html


def _due_datetime(due: date | datetime | None) -> datetime | None:
    """Vikunja only stores datetimes; a bare date means the end of that day."""
    if due is None or isinstance(due, datetime):
        return due
    return datetime.combine(due, time(23, 59), tzinfo=dt_util.get_default_time_zone())


def _todo_item(task: dict[str, Any]) -> TodoItem:
    return TodoItem(
        uid=str(task["id"]),
        summary=task.get("title"),
        status=(
            TodoItemStatus.COMPLETED if task.get("done") else TodoItemStatus.NEEDS_ACTION
        ),
        due=parse_date(task.get("due_date")),
        description=html_to_text(task.get("description")) or None,
        completed=parse_date(task.get("done_at")) if task.get("done") else None,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VikunjaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def add_new_projects() -> None:
        new = coordinator.data.projects.keys() - known
        known.update(new)
        async_add_entities(VikunjaProjectTodoList(coordinator, pid) for pid in new)

    add_new_projects()
    entry.async_on_unload(coordinator.async_add_listener(add_new_projects))


class VikunjaProjectTodoList(VikunjaEntity, TodoListEntity):
    """Open tasks plus those completed in the last week, for one project."""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator: VikunjaCoordinator, project_id: int) -> None:
        super().__init__(coordinator, f"project_{project_id}")
        self.project_id = project_id

    @property
    def available(self) -> bool:
        return super().available and self.project_id in self.coordinator.data.projects

    @property
    def name(self) -> str | None:
        return self.coordinator.data.paths.get(self.project_id, str(self.project_id))

    @property
    def todo_items(self) -> list[TodoItem]:
        tasks = self.coordinator.data.tasks_by_project.get(self.project_id, [])
        return [_todo_item(task) for task in tasks]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        project = self.coordinator.data.projects.get(self.project_id, {})
        return {
            "project_id": self.project_id,
            "identifier": project.get("identifier") or None,
            "url": self.coordinator.client.project_url(self.project_id),
        }

    async def async_create_todo_item(self, item: TodoItem) -> None:
        await self.async_create_task(
            title=item.summary or "",
            description=item.description,
            due_date=_due_datetime(item.due),
        )

    async def async_create_task(
        self,
        title: str,
        description: str | None = None,
        due_date: datetime | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
    ) -> ServiceResponse:
        """Also backs the vikunja.create_task service."""
        client = self.coordinator.client
        task: dict[str, Any] = {"title": title}
        if description:
            task["description"] = text_to_html(description)
        if due_date is not None:
            task["due_date"] = format_date(due_date)
        if priority is not None:
            task["priority"] = priority
        try:
            label_objs: list[dict[str, Any]] = []
            if labels:
                by_title = {
                    label["title"].casefold(): label
                    for label in await client.get_labels()
                }
                if missing := [l for l in labels if l.casefold() not in by_title]:
                    raise ServiceValidationError(
                        f"Vikunja: no label named {', '.join(missing)}"
                    )
                label_objs = [by_title[l.casefold()] for l in labels]
            created = await client.create_task(self.project_id, task)
            if label_objs:
                await client.set_task_labels(created["id"], label_objs)
                created["labels"] = label_objs
        except VikunjaApiError as err:
            raise HomeAssistantError(f"Vikunja: {err}") from err
        await self.coordinator.async_refresh()
        return self.coordinator.public(created)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid is None:
            raise HomeAssistantError("Vikunja: item has no uid")
        task = next(
            (
                t
                for t in self.coordinator.data.tasks_by_project.get(self.project_id, [])
                if str(t["id"]) == item.uid
            ),
            None,
        )
        if task is None:
            raise HomeAssistantError("Vikunja: task no longer exists, refresh and retry")

        # Only send what changed, so rich-text descriptions aren't flattened
        # just because a task was ticked off.
        seen = _todo_item(task)
        changes: dict[str, Any] = {}
        if item.summary != seen.summary:
            changes["title"] = item.summary
        if item.status is not None and item.status != seen.status:
            changes["done"] = item.status == TodoItemStatus.COMPLETED
        if item.due != seen.due:
            changes["due_date"] = format_date(_due_datetime(item.due))
        if (item.description or None) != seen.description:
            changes["description"] = text_to_html(item.description or "")
        if not changes:
            return
        try:
            await self.coordinator.client.update_task(task["id"], **changes)
        except VikunjaApiError as err:
            raise HomeAssistantError(f"Vikunja: {err}") from err
        await self.coordinator.async_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        try:
            for uid in uids:
                await self.coordinator.client.delete_task(int(uid))
        except VikunjaApiError as err:
            raise HomeAssistantError(f"Vikunja: {err}") from err
        finally:
            await self.coordinator.async_refresh()
