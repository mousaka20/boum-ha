"""Constants for the Boum integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)

DOMAIN: Final = "boum"

# --- Config / options keys ---------------------------------------------------
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 60  # seconds
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 3600

# How far back we look for telemetry on each poll. The Boum controller reports
# at low frequency, so an hour gives us a comfortable buffer to always have a
# "latest" value to display.
TELEMETRY_LOOKBACK: Final = timedelta(hours=1)

# --- Manufacturer / device info ---------------------------------------------
MANUFACTURER: Final = "Boum"
MODEL: Final = "Boum Controller"

# --- Device commands (mirrors DEVICE_COMMANDS in boum.api_client.v1.models) --
COMMAND_RESET_WIFI: Final = "resetWiFiCredentials"
COMMAND_UPDATE_CERTIFICATE: Final = "updateCertificate"
COMMAND_RESTART_DEVICE: Final = "restartDevice"
COMMAND_US_INCR_STRENGTH: Final = "distUsIncrStrength"
COMMAND_US_DECR_STRENGTH: Final = "distUsDecrStrength"
COMMAND_US_READ_STRENGTH: Final = "distUsReadStrength"
COMMAND_US_CLEAN_LOOP: Final = "distUsCleanLoop"

# Human-readable labels for the buttons we expose.
COMMAND_LABELS: Final[dict[str, str]] = {
    COMMAND_RESTART_DEVICE: "Restart device",
    COMMAND_US_CLEAN_LOOP: "Ultrasonic clean loop",
    COMMAND_US_READ_STRENGTH: "Read ultrasonic strength",
    COMMAND_US_INCR_STRENGTH: "Increase ultrasonic strength",
    COMMAND_US_DECR_STRENGTH: "Decrease ultrasonic strength",
    COMMAND_RESET_WIFI: "Reset WiFi credentials",
    COMMAND_UPDATE_CERTIFICATE: "Update certificate",
}

# Buttons that are potentially disruptive get hidden in the diagnostic category
# but are still available to power users.
DIAGNOSTIC_COMMANDS: Final[set[str]] = {
    COMMAND_RESET_WIFI,
    COMMAND_UPDATE_CERTIFICATE,
    COMMAND_US_INCR_STRENGTH,
    COMMAND_US_DECR_STRENGTH,
    COMMAND_US_READ_STRENGTH,
}

# --- Flag → binary_sensor mapping -------------------------------------------
# Each tuple is (attribute on DeviceFlagsModel, friendly name, device_class).
# Flag values are ints in the SDK; we treat 0 (or None) as "off", anything
# else as "on".
FLAG_DEFINITIONS: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("water_leakage", "Water leakage", "moisture"),
    ("water_level", "Water tank low", "problem"),
    ("low_battery", "Low battery", "battery"),
    ("draws_air", "Draws air", "problem"),
    ("slow_recharge", "Slow recharge", "problem"),
    ("high_water_usage", "High water usage", "problem"),
    ("low_water_usage", "Low water usage", "problem"),
    ("poor_wifi", "Poor WiFi", "problem"),
    ("poor_us", "Poor ultrasonic signal", "problem"),
    ("offline_warning", "Offline", "connectivity"),
)
# Flags whose semantic meaning is inverted relative to the device_class
# (e.g. CONNECTIVITY: True == connected, but `offline_warning` is True == offline).
INVERTED_FLAGS: Final[set[str]] = {"offline_warning"}

# --- Telemetry sensor catalogue ---------------------------------------------
# The /devices/{id}/data endpoint returns an arbitrary set of time-series
# keyed by name. We provide nice metadata for the ones we know about; any
# unknown key still appears as a generic numeric sensor.
#
# Each entry: SDK telemetry key -> (friendly name, unit, device_class, state_class, icon)
TELEMETRY_DEFINITIONS: Final[dict[str, dict]] = {
    # Tank / water
    "waterLevel": {
        "name": "Water level",
        "unit": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:water-percent",
    },
    "tankLevel": {
        "name": "Tank level",
        "unit": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cup-water",
    },
    "waterConsumption": {
        "name": "Water consumption",
        "unit": UnitOfVolume.LITERS,
        "device_class": SensorDeviceClass.WATER,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:water",
    },
    "distUs": {
        "name": "Ultrasonic distance",
        "unit": UnitOfLength.CENTIMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:ruler",
    },
    # Climate
    "temperature": {
        "name": "Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "humidity": {
        "name": "Humidity",
        "unit": PERCENTAGE,
        "device_class": SensorDeviceClass.HUMIDITY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # Power
    "batteryVoltage": {
        "name": "Battery voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "batteryLevel": {
        "name": "Battery level",
        "unit": PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "solarVoltage": {
        "name": "Solar voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:solar-power",
    },
    # Pump
    "pumpRuntime": {
        "name": "Pump runtime",
        "unit": UnitOfTime.SECONDS,
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:pump",
    },
}
