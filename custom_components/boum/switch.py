"""Switch platform: pump on/off, refill-slot enables, leakage detection."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, REFILL_SLOT_DEFAULT_ENABLED, REFILL_SLOTS
from .coordinator import BoumDataUpdateCoordinator
from .entity import BoumEntity
from .extra_api import BoumExtraApi, REFILL_SLOT_KEYS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoumDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new: list[SwitchEntity] = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            new.append(BoumPumpSwitch(coordinator, device_id))
            for slot in REFILL_SLOTS:
                new.append(BoumRefillSlotSwitch(coordinator, device_id, slot))
            new.append(BoumLeakageDetectionSwitch(coordinator, device_id))
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


class BoumRefillSlotSwitch(BoumEntity, SwitchEntity):
    """Enable/disable one of the three daily refill slots.

    The Boum controller can refill up to three times a day at independent
    times — each slot has its own enable flag (`dailyRefill`,
    `dailyRefillTwo`, `dailyRefillThree`) and time. The SDK doesn't model
    them, so we read and write through the raw API. The matching time-of-day
    is exposed by a `Time` entity in `time.py`.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: BoumDataUpdateCoordinator,
        device_id: str,
        slot: int,
    ) -> None:
        super().__init__(coordinator, device_id, f"refill_slot_{slot}_enabled")
        self._slot = slot
        self._attr_name = f"Refill slot {slot}"
        # Slots beyond the primary start disabled in the UI — most users
        # only configure one.
        if slot not in REFILL_SLOT_DEFAULT_ENABLED:
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool | None:
        snap = self.snapshot
        if snap is None:
            return None
        enabled, _ = BoumExtraApi.parse_refill_slot(snap.raw_reported, self._slot)
        if enabled is None:
            # Fall back to the desired state if the reported half hasn't
            # caught up yet — better than showing unknown forever.
            enabled, _ = BoumExtraApi.parse_refill_slot(snap.raw_desired, self._slot)
        return enabled

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snap = self.snapshot
        if snap is None:
            return False
        # Only mark available if the slot's keys appear somewhere in the
        # shadow — that way devices that don't support slot 2/3 hide them.
        enabled_key, time_key = REFILL_SLOT_KEYS[self._slot]
        return (
            enabled_key in snap.raw_reported
            or time_key in snap.raw_reported
            or enabled_key in snap.raw_desired
            or time_key in snap.raw_desired
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_set_refill_slot(
            self._device_id, self._slot, enabled=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_set_refill_slot(
            self._device_id, self._slot, enabled=False
        )
        await self.coordinator.async_request_refresh()


class BoumLeakageDetectionSwitch(BoumEntity, SwitchEntity):
    """Toggle the controller's `leakageDetection` feature (CLI's `tune` field)."""

    _attr_translation_key = "leakage_detection"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "leakage_detection")

    @property
    def is_on(self) -> bool | None:
        snap = self.snapshot
        if snap is None:
            return None
        value = BoumExtraApi.parse_on_off(snap.raw_reported, "leakageDetection")
        if value is None:
            value = BoumExtraApi.parse_on_off(snap.raw_desired, "leakageDetection")
        return value

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snap = self.snapshot
        if snap is None:
            return False
        return (
            "leakageDetection" in snap.raw_reported
            or "leakageDetection" in snap.raw_desired
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_tune(
            self._device_id, leakage_detection=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_tune(
            self._device_id, leakage_detection=False
        )
        await self.coordinator.async_request_refresh()
