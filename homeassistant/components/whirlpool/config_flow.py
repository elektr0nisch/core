"""Config flow for Whirlpool Sixth Sense integration."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from whirlpool.auth import Auth
from whirlpool.backendselector import BackendSelector

from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_PASSWORD, CONF_REGION, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_REGIONS_MAP, DOMAIN
from .util import get_brand_for_region

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_REGION): vol.In(list(CONF_REGIONS_MAP)),
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def validate_input(
    hass: core.HomeAssistant, data: dict[str, str]
) -> dict[str, str]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    region = CONF_REGIONS_MAP[data[CONF_REGION]]
    brand = get_brand_for_region(region)
    backend_selector = BackendSelector(brand, region)
    auth = Auth(backend_selector, data[CONF_USERNAME], data[CONF_PASSWORD])
    try:
        await auth.do_auth()
    except (asyncio.TimeoutError, aiohttp.ClientConnectionError) as exc:
        raise CannotConnect from exc

    if not auth.is_access_token_valid():
        raise InvalidAuth

    return {"title": data[CONF_USERNAME]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Whirlpool Sixth Sense."""

    VERSION = 1
    entry: config_entries.ConfigEntry | None

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle re-authentication with Whirlpool Sixth Sense."""

        self.entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm re-authentication with Whirlpool Sixth Sense."""
        errors: dict[str, str] = {}

        if user_input:
            assert self.entry is not None
            password = user_input[CONF_PASSWORD]
            data = {
                **self.entry.data,
                CONF_PASSWORD: password,
            }

            try:
                await validate_input(self.hass, data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except (CannotConnect, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        CONF_PASSWORD: password,
                    },
                )
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
        )

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(
                user_input[CONF_USERNAME].lower(), raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
