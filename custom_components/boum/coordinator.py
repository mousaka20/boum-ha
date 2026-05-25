"""Data update coordinator for the Boum integration."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoumAuthError, BoumClient, BoumConnectionError, BoumDeviceSnapshot
from .const import DOMAIN, TELEMETRY_LOOKBACK

_LOGGER = logging.getLogger(__name__)


class BoumDataUpdateCoordinator(DataUpdateCoordinator[dict[str, BoumDeviceSnapshot]]):
    """Polls Boum for the user's claimed devices on a regular interval.

    The coordinator's ``data`` is a dict keyed by device id, so any platform
    can look up its device's snapshot in O(1).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: BoumClient,
        scan_interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.entry = entry
        self.client = client
        # Populated on first refresh; entities query it via `device_ids`.
        self._device_ids: list[str] = []

    @property
    def device_ids(self) -> list[str]:
        return list(self._device_ids)

    async def _async_update_data(self) -> dict[str, BoumDeviceSnapshot]:
        try:
            # Re-list claimed devices each cycle so users adding/removing a
            # device on the Boum side see it reflected without restarting HA.
            self._device_ids = await self.client.async_list_claimed_device_ids()

            snapshots: dict[str, BoumDeviceSnapshot] = {}
            for device_id in self._device_ids:
                snapshots[device_id] = await self.client.async_fetch_snapshot(
                    device_id, TELEMETRY_LOOKBACK
                )
            return snapshots
        except BoumAuthError as err:
            # Trigger re-auth flow in the UI.
            raise ConfigEntryAuthFailed(str(err)) from err
        except BoumConnectionError as err:
            raise UpdateFailed(str(err)) from err
