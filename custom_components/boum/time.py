"""Time platform: daily refill time (SDK single field) and slotted refill times."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
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
        new: list[TimeEntity] = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            new.append(BoumRefillTime(coordinator, device_id))
            for slot in REFILL_SLOTS:
                new.append(BoumRefillSlotTime(coordinator, device_id, slot))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumRefillTime(BoumEntity, TimeEntity):
    """The legacy single ``refillTime`` field modelled by the SDK.

    Newer firmwares use the slotted refill scheme below; older ones use this
    single field. We expose both — the unused one stays unavailable.
    """

    _attr_translation_key = "refill_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-time-four-outline"
    # Disabled by default — most controllers populate the slot-based fields
    # instead. Users on the legacy schema can enable it from the registry.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "refill_time")

    @property
    def native_value(self) -> dt_time | None:
        snap = self.snapshot
        if snap is None or snap.reported_state is None:
            return None
        return snap.reported_state.refill_time

    async def async_set_value(self, value: dt_time) -> None:
        normalized = dt_time(value.hour, value.minute)
        await self.coordinator.client.async_patch_desired_state(
            self._device_id, refill_time=normalized
        )
        await self.coordinator.async_request_refresh()


class BoumRefillSlotTime(BoumEntity, TimeEntity):
    """Refill time-of-day for a specific slot (1, 2 or 3)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(
        self,
        coordinator: BoumDataUpdateCoordinator,
        device_id: str,
        slot: int,
    ) -> None:
        super().__init__(coordinator, device_id, f"refill_slot_{slot}_time")
        self._slot = slot
        self._attr_name = f"Refill slot {slot} time"
        if slot not in REFILL_SLOT_DEFAULT_ENABLED:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> dt_time | None:
        snap = self.snapshot
        if snap is None:
            return None
        _, value = BoumExtraApi.parse_refill_slot(snap.raw_reported, self._slot)
        if value is None:
            _, value = BoumExtraApi.parse_refill_slot(snap.raw_desired, self._slot)
        return value

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        snap = self.snapshot
        if snap is None:
            return False
        enabled_key, time_key = REFILL_SLOT_KEYS[self._slot]
        return (
            enabled_key in snap.raw_reported
            or time_key in snap.raw_reported
            or enabled_key in snap.raw_desired
            or time_key in snap.raw_desired
        )

    async def async_set_value(self, value: dt_time) -> None:
        normalized = dt_time(value.hour, value.minute)
        await self.coordinator.client.async_set_refill_slot(
            self._device_id, self._slot, refill_time=normalized
        )
        await self.coordinator.async_request_refresh()
