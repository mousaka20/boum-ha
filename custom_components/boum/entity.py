"""Base entity for Boum integrations."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import BoumDeviceSnapshot
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import BoumDataUpdateCoordinator


class BoumEntity(CoordinatorEntity[BoumDataUpdateCoordinator]):
    """Shared behaviour for all Boum entities tied to a specific device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BoumDataUpdateCoordinator,
        device_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        # entity unique id: <device_id>-<key>. Keys are stable strings owned
        # by each platform (e.g. "pump", "flag_low_battery", "telemetry_temperature").
        self._attr_unique_id = f"{device_id}-{key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"Boum {device_id[:8]}",
            configuration_url="https://boum.garden/",
        )

    @property
    def snapshot(self) -> BoumDeviceSnapshot | None:
        """Return the latest snapshot for this entity's device, if any."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        # An entity is available only when its device was present in the last
        # successful poll.
        return super().available and self.snapshot is not None
