"""Vikunja integration: a to-do list per project, task sensors, a calendar, services."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import VikunjaApiClient, VikunjaApiError, VikunjaAuthError
from .const import DOMAIN
from .coordinator import VikunjaConfigEntry, VikunjaCoordinator
from .models import text_to_html

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR, Platform.TODO]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

CREATE_TASK_SCHEMA = {
    vol.Required("title"): cv.string,
    vol.Optional("description"): cv.string,
    vol.Optional("due_date"): vol.All(cv.datetime, dt_util.as_local),
    vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
    vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
}

GET_TASKS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("filter", default="done = false"): cv.string,
        vol.Optional("search"): cv.string,
    }
)

ADD_COMMENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required("task_id"): vol.Coerce(int),
        vol.Required("comment"): cv.string,
    }
)


def _coordinator(hass: HomeAssistant, entry_id: str | None) -> VikunjaCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if entry_id is None or entry.entry_id == entry_id:
            return entry.runtime_data
    if entry_id is None:
        raise ServiceValidationError("No loaded Vikunja config entry")
    raise ServiceValidationError(f"Vikunja config entry {entry_id} is not loaded")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services, which pick an account by config entry or to-do entity."""

    async def get_tasks(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        try:
            tasks = await coordinator.client.get_tasks(
                call.data["filter"], call.data.get("search")
            )
        except VikunjaApiError as err:
            raise HomeAssistantError(f"Vikunja: {err}") from err
        return {"tasks": [coordinator.public(t) for t in tasks]}

    async def add_comment(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        try:
            comment = await coordinator.client.add_comment(
                call.data["task_id"], text_to_html(call.data["comment"])
            )
        except VikunjaApiError as err:
            raise HomeAssistantError(f"Vikunja: {err}") from err
        return {"id": comment.get("id"), "task_id": call.data["task_id"]}

    hass.services.async_register(
        DOMAIN,
        "get_tasks",
        get_tasks,
        GET_TASKS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "add_comment",
        add_comment,
        ADD_COMMENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "create_task",
        entity_domain=TODO_DOMAIN,
        schema=CREATE_TASK_SCHEMA,
        func="async_create_task",
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VikunjaConfigEntry) -> bool:
    client = VikunjaApiClient(
        async_get_clientsession(hass, entry.data.get(CONF_VERIFY_SSL, True)),
        entry.data[CONF_URL],
        entry.data[CONF_API_TOKEN],
    )
    try:
        await client.get_info()
        user = await client.get_user()
    except VikunjaAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except VikunjaApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = VikunjaCoordinator(hass, entry, client, user)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VikunjaConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
