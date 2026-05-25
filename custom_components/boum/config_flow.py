"""Config flow for Boum."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .api import BoumAuthError, BoumClient, BoumConnectionError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)


async def _async_try_login(hass, email: str, password: str) -> None:
    """Validate credentials by signing in and listing claimed devices."""
    client = BoumClient(hass, email, password)
    try:
        await client.async_connect()
        # Touching the API once confirms the token is valid end-to-end.
        await client.async_list_claimed_device_ids()
    finally:
        await client.async_close()


class BoumConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Boum."""

    VERSION = 1

    def __init__(self) -> None:
        # Used by the re-auth path so we can update the existing entry.
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial user-driven step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            # One entry per account — emails are unique on the Boum side.
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            try:
                await _async_try_login(self.hass, email, password)
            except BoumAuthError:
                errors["base"] = "invalid_auth"
            except BoumConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 — surface as generic error
                _LOGGER.exception("Unexpected error validating Boum credentials")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    # -- re-auth -------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._reauth_entry is not None
        errors: dict[str, str] = {}
        email = self._reauth_entry.data[CONF_EMAIL]

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                await _async_try_login(self.hass, email, password)
            except BoumAuthError:
                errors["base"] = "invalid_auth"
            except BoumConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Boum re-auth")
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={**self._reauth_entry.data, CONF_PASSWORD: password},
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            description_placeholders={"email": email},
            errors=errors,
        )

    # -- options -------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return BoumOptionsFlow(entry)


class BoumOptionsFlow(OptionsFlow):
    """Options flow — currently just the scan interval."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
        )
