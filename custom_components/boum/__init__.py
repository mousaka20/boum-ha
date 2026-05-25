"""The Boum integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import BoumAuthError, BoumClient, BoumConnectionError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import BoumDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Boum from a config entry."""
    email: str = entry.data[CONF_EMAIL]
    password: str = entry.data[CONF_PASSWORD]
    scan_interval: int = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    client = BoumClient(hass, email, password)
    try:
        await client.async_connect()
    except BoumAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except BoumConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = BoumDataUpdateCoordinator(hass, entry, client, scan_interval)

    # Run the first refresh inline so we fail fast on bad creds / no devices.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-create the entry when the user tweaks options (e.g. scan interval).
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: BoumDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.async_close()
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
