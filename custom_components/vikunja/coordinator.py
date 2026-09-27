"""Polls Vikunja for projects, open tasks, and recently completed tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VikunjaApiClient, VikunjaApiError, VikunjaAuthError
from .const import DOMAIN, RECENTLY_DONE, SCAN_INTERVAL
from .models import project_paths, public_task

_LOGGER = logging.getLogger(__name__)

type VikunjaConfigEntry = ConfigEntry[VikunjaCoordinator]


@dataclass
class VikunjaData:
    """Snapshot of one account's Vikunja state."""

    # Real projects only: Vikunja lists Favorites and saved filters with ids <= 0.
    projects: dict[int, dict[str, Any]]
    # Project id -> "Parent / Child" title.
    paths: dict[int, str]
    # Open tasks in real projects.
    open_tasks: list[dict[str, Any]]
    # Open and recently completed tasks per project.
    tasks_by_project: dict[int, list[dict[str, Any]]] = field(default_factory=dict)


class VikunjaCoordinator(DataUpdateCoordinator[VikunjaData]):
    """Fetches everything the entities need in one pass."""

    config_entry: VikunjaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VikunjaConfigEntry,
        client: VikunjaApiClient,
        user: dict[str, Any] | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.user = user

    def public(self, task: dict[str, Any]) -> dict[str, Any]:
        return public_task(task, self.client.frontend_url, self.data.paths)

    async def _async_update_data(self) -> VikunjaData:
        try:
            projects = await self.client.get_projects()
            open_tasks = await self.client.get_tasks("done = false")
            done_tasks = await self.client.get_tasks(
                f"done = true && done_at > {RECENTLY_DONE}"
            )
        except VikunjaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except VikunjaApiError as err:
            raise UpdateFailed(str(err)) from err

        real = {p["id"]: p for p in projects if p.get("id", 0) > 0}
        open_tasks = [t for t in open_tasks if t.get("project_id") in real]
        by_project: dict[int, list[dict[str, Any]]] = {pid: [] for pid in real}
        for task in (*open_tasks, *done_tasks):
            if (pid := task.get("project_id")) in by_project:
                by_project[pid].append(task)

        return VikunjaData(
            projects=real,
            paths=project_paths(list(real.values())),
            open_tasks=open_tasks,
            tasks_by_project=by_project,
        )
