"""Base entity for Vikunja."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VikunjaCoordinator


class VikunjaEntity(CoordinatorEntity[VikunjaCoordinator]):
    """All Vikunja entities hang off one service device per config entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VikunjaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Vikunja",
            model="Vikunja server",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.frontend_url,
        )
