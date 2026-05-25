"""Number platform: refill interval and max pump duration."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
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
        new = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            new.extend(
                [
                    BoumRefillIntervalNumber(coordinator, device_id),
                    BoumMaxPumpDurationNumber(coordinator, device_id),
                ]
            )
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumRefillIntervalNumber(BoumEntity, NumberEntity):
    """How many days between refills (1..30 per SDK constraints)."""

    _attr_translation_key = "refill_interval_days"
    _attr_native_min_value = 1
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-refresh"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "refill_interval_days")

    @property
    def native_value(self) -> float | None:
        snap = self.snapshot
        if snap is None or snap.reported_state is None:
            return None
        return snap.reported_state.refill_interval_days

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_patch_desired_state(
            self._device_id, refill_interval_days=int(value)
        )
        await self.coordinator.async_request_refresh()


class BoumMaxPumpDurationNumber(BoumEntity, NumberEntity):
    """Pump runtime cap in minutes (1..1439 per SDK constraints)."""

    _attr_translation_key = "max_pump_duration_minutes"
    _attr_native_min_value = 1
    _attr_native_max_value = 1439
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:timer-cog"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "max_pump_duration_minutes")

    @property
    def native_value(self) -> float | None:
        snap = self.snapshot
        if snap is None or snap.reported_state is None:
            return None
        return snap.reported_state.max_pump_duration_minutes

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_patch_desired_state(
            self._device_id, max_pump_duration_minutes=int(value)
        )
        await self.coordinator.async_request_refresh()
