"""Switch platform: pump on/off."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
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
        new: list[BoumPumpSwitch] = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            new.append(BoumPumpSwitch(coordinator, device_id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumPumpSwitch(BoumEntity, SwitchEntity):
    """The controller's pump.

    `reported_state.pump_state` is what's actually happening; setting
    `desired_state.pump_state` asks the controller to flip.
    """

    _attr_translation_key = "pump"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "pump")

    @property
    def is_on(self) -> bool | None:
        snap = self.snapshot
        if snap is None or snap.reported_state is None:
            return None
        return snap.reported_state.pump_state

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_patch_desired_state(
            self._device_id, pump_state=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_patch_desired_state(
            self._device_id, pump_state=False
        )
        await self.coordinator.async_request_refresh()
