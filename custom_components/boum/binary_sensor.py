"""Binary sensor platform: device flags (warnings/alerts)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FLAG_DEFINITIONS, INVERTED_FLAGS
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
        new: list[BoumFlagBinarySensor] = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            for attr, name, device_class in FLAG_DEFINITIONS:
                new.append(
                    BoumFlagBinarySensor(coordinator, device_id, attr, name, device_class)
                )
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumFlagBinarySensor(BoumEntity, BinarySensorEntity):
    """A single flag from DeviceFlagsModel surfaced as a binary sensor.

    Flag values are ints in the SDK; we treat 0/None as off and anything
    truthy as on. A handful of flags (``offline_warning``) are semantically
    inverted relative to their device_class — Boum reports "offline_warning=1"
    meaning *offline*, while HA's CONNECTIVITY device_class wants True = connected.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: BoumDataUpdateCoordinator,
        device_id: str,
        flag_attr: str,
        friendly_name: str,
        device_class: str | None,
    ) -> None:
        super().__init__(coordinator, device_id, f"flag_{flag_attr}")
        self._flag_attr = flag_attr
        self._attr_name = friendly_name
        if device_class is not None:
            try:
                self._attr_device_class = BinarySensorDeviceClass(device_class)
            except ValueError:
                # If someone changes the const table and uses a label HA
                # doesn't recognise, just skip the class — don't crash.
                self._attr_device_class = None
        self._inverted = flag_attr in INVERTED_FLAGS

    @property
    def is_on(self) -> bool | None:
        snap = self.snapshot
        if snap is None or snap.flags is None:
            return None
        raw = getattr(snap.flags, self._flag_attr, None)
        if raw is None:
            return None
        active = bool(raw)
        return not active if self._inverted else active
