"""Number platform: SDK-modelled fields + CLI-only tuning numbers.

Existing SDK-backed entities:
  - Refill interval (days)
  - Max pump duration (minutes)

CLI-only entities (raw API):
  - Max publication interval below 90% battery (seconds)
  - Max publication interval above 90% battery (seconds)
  - Minimum flow rate (litres/min — the API just stores a float)
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BoumDataUpdateCoordinator
from .entity import BoumEntity
from .extra_api import BoumExtraApi


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoumDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new: list[NumberEntity] = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            new.extend(
                [
                    BoumRefillIntervalNumber(coordinator, device_id),
                    BoumMaxPumpDurationNumber(coordinator, device_id),
                    BoumMaxPubIntervalNumber(coordinator, device_id),
                    BoumHMaxPubIntervalNumber(coordinator, device_id),
                    BoumMinFlowRateNumber(coordinator, device_id),
                ]
            )
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


# -- SDK-modelled --------------------------------------------------------------


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


# -- CLI-only (raw API) --------------------------------------------------------


class _BoumTuningPubIntervalNumber(BoumEntity, NumberEntity):
    """Base class for the two publication-interval tunables.

    The API stores them as ``"<n>s"`` strings; we expose them as plain
    integers in seconds with a 5 s..1 h range — that covers the documented
    examples (60 s, 90 s) with plenty of headroom.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 5
    _attr_native_max_value = 3600
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:upload-network-outline"

    _api_key: str = ""  # set by subclass

    @property
    def native_value(self) -> float | None:
        snap = self.snapshot
        if snap is None:
            return None
        value = BoumExtraApi.parse_duration_seconds(snap.raw_reported, self._api_key)
        if value is None:
            value = BoumExtraApi.parse_duration_seconds(snap.raw_desired, self._api_key)
        return value

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snap = self.snapshot
        if snap is None:
            return False
        return self._api_key in snap.raw_reported or self._api_key in snap.raw_desired


class BoumMaxPubIntervalNumber(_BoumTuningPubIntervalNumber):
    """``maxPubInterval`` — max time between measurements at <90% battery."""

    _attr_name = "Max publication interval (low battery)"
    _api_key = "maxPubInterval"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "max_pub_interval_seconds")

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_tune(
            self._device_id, max_pub_interval_seconds=int(value)
        )
        await self.coordinator.async_request_refresh()


class BoumHMaxPubIntervalNumber(_BoumTuningPubIntervalNumber):
    """``hMaxPubInterval`` — max time between measurements at >90% battery."""

    _attr_name = "Max publication interval (high battery)"
    _api_key = "hMaxPubInterval"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "h_max_pub_interval_seconds")

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_tune(
            self._device_id, h_max_pub_interval_seconds=int(value)
        )
        await self.coordinator.async_request_refresh()


class BoumMinFlowRateNumber(BoumEntity, NumberEntity):
    """``minFlowRate`` — leak detection threshold (CLI example: 0.11)."""

    _attr_name = "Minimum flow rate"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0.0
    _attr_native_max_value = 10.0
    _attr_native_step = 0.01
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:water-pump"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "min_flow_rate")

    @property
    def native_value(self) -> float | None:
        snap = self.snapshot
        if snap is None:
            return None
        value = BoumExtraApi.parse_number(snap.raw_reported, "minFlowRate")
        if value is None:
            value = BoumExtraApi.parse_number(snap.raw_desired, "minFlowRate")
        return value

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snap = self.snapshot
        if snap is None:
            return False
        return "minFlowRate" in snap.raw_reported or "minFlowRate" in snap.raw_desired

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_tune(
            self._device_id, min_flow_rate=float(value)
        )
        await self.coordinator.async_request_refresh()
