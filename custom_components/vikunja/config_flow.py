"""Config flow for Vikunja."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    VikunjaApiClient,
    VikunjaApiError,
    VikunjaAuthError,
    VikunjaConnectionError,
)
from .const import DEFAULT_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _unique_id(url: str, token: str, user: dict[str, Any] | None) -> str:
    # API tokens may not be allowed to read /user; fall back to the token itself.
    if user:
        return f"{url}/user/{user['id']}"
    return f"{url}/token/{hashlib.sha256(token.encode()).hexdigest()[:16]}"


class VikunjaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Vikunja URL and an API token, and check they work."""

    VERSION = 1

    async def _validate(
        self, data: dict[str, Any], errors: dict[str, str]
    ) -> tuple[str, str] | None:
        """Return (unique id, title), or fill in errors."""
        client = VikunjaApiClient(
            async_get_clientsession(self.hass, data.get(CONF_VERIFY_SSL, True)),
            data[CONF_URL],
            data[CONF_API_TOKEN],
        )
        try:
            await client.get_info()
            await client.get_projects()
            await client.get_tasks("done = false")
            user = await client.get_user()
        except VikunjaAuthError:
            errors["base"] = "invalid_auth"
        except VikunjaConnectionError:
            errors["base"] = "cannot_connect"
        except VikunjaApiError:
            errors["base"] = "invalid_response"
        except Exception:
            _LOGGER.exception("Unexpected error while testing Vikunja")
            errors["base"] = "unknown"
        else:
            name = (user or {}).get("username")
            return (
                _unique_id(data[CONF_URL], data[CONF_API_TOKEN], user),
                f"Vikunja ({name})" if name else "Vikunja",
            )
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_URL] = user_input[CONF_URL].rstrip("/")
            if result := await self._validate(user_input, errors):
                unique_id, title = result
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): str,
                        vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR,
                        vol.Required(CONF_VERIFY_SSL, default=True): bool,
                    }
                ),
                user_input or {CONF_URL: DEFAULT_URL},
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            data = {**entry.data, **user_input}
            if await self._validate(data, errors):
                # A new token can't be matched to the old one when /user is off
                # limits, so the account isn't checked here.
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            description_placeholders={CONF_URL: entry.data[CONF_URL]},
            errors=errors,
        )
