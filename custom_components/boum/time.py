"""Time platform: daily refill time."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BoumDataUpdateCoordinator
from .entity import BoumEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoumDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [
            BoumRefillTime(coordinator, did)
            for did in coordinator.device_ids
            if did not in known
        ]
        known.update(coordinator.device_ids)
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumRefillTime(BoumEntity, TimeEntity):
    """The time of day at which the controller's daily refill cycle runs."""

    _attr_translation_key = "refill_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "refill_time")

    @property
    def native_value(self) -> dt_time | None:
        snap = self.snapshot
        if snap is None or snap.reported_state is None:
            return None
        return snap.reported_state.refill_time

    async def async_set_value(self, value: dt_time) -> None:
        # The SDK only persists hour/minute resolution. We pass a fresh
        # `time` to avoid surprises if the user picked a non-zero seconds.
        normalized = dt_time(value.hour, value.minute)
        await self.coordinator.client.async_patch_desired_state(
            self._device_id, refill_time=normalized
        )
        await self.coordinator.async_request_refresh()
