"""Button platform: device commands (restart, ultrasonic, etc.)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COMMAND_LABELS,
    COMMAND_RESTART_DEVICE,
    DIAGNOSTIC_COMMANDS,
    DOMAIN,
)
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
        new: list[BoumCommandButton] = []
        for device_id in coordinator.device_ids:
            if device_id in known:
                continue
            known.add(device_id)
            for command, label in COMMAND_LABELS.items():
                new.append(BoumCommandButton(coordinator, device_id, command, label))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class BoumCommandButton(BoumEntity, ButtonEntity):
    """One button per command in ``DEVICE_COMMANDS``."""

    def __init__(
        self,
        coordinator: BoumDataUpdateCoordinator,
        device_id: str,
        command: str,
        label: str,
    ) -> None:
        super().__init__(coordinator, device_id, f"command_{command}")
        self._command = command
        self._attr_name = label
        if command == COMMAND_RESTART_DEVICE:
            self._attr_device_class = ButtonDeviceClass.RESTART
        if command in DIAGNOSTIC_COMMANDS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            # Diagnostic buttons start disabled — users opt in via the
            # entity registry if they want them visible by default.
            self._attr_entity_registry_enabled_default = False

    async def async_press(self) -> None:
        await self.coordinator.client.async_send_command(self._device_id, self._command)
        # Don't immediately refresh — many of these commands take time to
        # take effect. The next regular poll will pick up any state changes.
