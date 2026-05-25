"""Sensor platform: firmware version + dynamic telemetry sensors."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TELEMETRY_DEFINITIONS
from .coordinator import BoumDataUpdateCoordinator
from .entity import BoumEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BoumDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Track what we've already created. Telemetry sensors are dynamic — keys
    # only appear once the device has reported data for them — so we re-check
    # on every coordinator update.
    created_firmware: set[str] = set()
    created_owner: set[str] = set()
    created_telemetry: set[tuple[str, str]] = set()

    @callback
    def _add_new() -> None:
        new: list[SensorEntity] = []
        for device_id in coordinator.device_ids:
            if device_id not in created_firmware:
                created_firmware.add(device_id)
                new.append(BoumFirmwareSensor(coordinator, device_id))
            if device_id not in created_owner:
                created_owner.add(device_id)
                new.append(BoumOwnerSensor(coordinator, device_id))

            snap = coordinator.data.get(device_id) if coordinator.data else None
            if snap is None:
                continue
            for key in snap.telemetry_latest:
                marker = (device_id, key)
                if marker in created_telemetry:
                    continue
                created_telemetry.add(marker)
                new.append(BoumTelemetrySensor(coordinator, device_id, key))

        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumFirmwareSensor(BoumEntity, SensorEntity):
    """Reported firmware version of the controller."""

    _attr_translation_key = "firmware_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "firmware_version")

    @property
    def native_value(self) -> str | None:
        snap = self.snapshot
        if snap is None or snap.reported_state is None:
            return None
        return snap.reported_state.firmware_version


class BoumOwnerSensor(BoumEntity, SensorEntity):
    """Owner of the device (from ``GET /devices/{id}/owner``).

    Disabled by default — most users only care for diagnostics. The full
    owner record is exposed as a state attribute so it can still be picked
    up by templates if needed.
    """

    _attr_translation_key = "owner"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:account"

    def __init__(self, coordinator: BoumDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "owner")

    @property
    def native_value(self) -> str | None:
        snap = self.snapshot
        if snap is None or snap.owner is None:
            return None
        # Prefer email > id > anything stringy.
        for key in ("email", "id", "userId", "ownerId", "name"):
            value = snap.owner.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        snap = self.snapshot
        if snap is None or snap.owner is None:
            return None
        # Only surface JSON-friendly scalar fields. Anything else (nested
        # objects, raw timestamps) is dropped to keep the attribute table
        # clean.
        return {
            k: v
            for k, v in snap.owner.items()
            if isinstance(v, (str, int, float, bool))
        }


class BoumTelemetrySensor(BoumEntity, SensorEntity):
    """A single telemetry time-series exposed as a sensor.

    The Boum API returns timeseries keyed by name. We don't hard-code the
    list because firmware updates may add new ones; instead we look the key
    up in ``TELEMETRY_DEFINITIONS`` for nice metadata and fall back to a
    generic numeric sensor for anything unknown.
    """

    def __init__(
        self,
        coordinator: BoumDataUpdateCoordinator,
        device_id: str,
        telemetry_key: str,
    ) -> None:
        super().__init__(coordinator, device_id, f"telemetry_{telemetry_key}")
        self._telemetry_key = telemetry_key

        definition = TELEMETRY_DEFINITIONS.get(telemetry_key)
        if definition is not None:
            self._attr_name = definition["name"]
            if "unit" in definition:
                self._attr_native_unit_of_measurement = definition["unit"]
            if "device_class" in definition:
                self._attr_device_class = definition["device_class"]
            if "state_class" in definition:
                self._attr_state_class = definition["state_class"]
            if "icon" in definition:
                self._attr_icon = definition["icon"]
        else:
            # Unknown key — show it as-is, default to a measurement sensor.
            self._attr_name = _humanize(telemetry_key)
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | int | None:
        snap = self.snapshot
        if snap is None:
            return None
        return snap.telemetry_latest.get(self._telemetry_key)


def _humanize(key: str) -> str:
    """Turn ``waterLevel`` into ``Water level``.

    Used as a sensible default for telemetry keys we don't have explicit
    metadata for.
    """
    if not key:
        return key
    # Split camelCase to spaces.
    out: list[str] = []
    for i, ch in enumerate(key):
        if i > 0 and ch.isupper() and not key[i - 1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).strip().capitalize()
