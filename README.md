# Boum for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) custom integration for the [Boum](https://boum.garden/) smart solar-powered plant irrigation system, built on top of the official [`boum` Python SDK](https://github.com/boum-garden/sdk).

> Boum is a Swiss smart irrigation system: a solar-powered controller pumps water from a tank into self-watering pots equipped with capillary wicks. The controller is cloud-connected, exposes telemetry (water level, climate, battery, ...), and can be configured via the Boum app — and now from Home Assistant.

## Features

For every Boum controller claimed to your account this integration creates:

| Platform | Entity | Description |
| --- | --- | --- |
| `switch` | **Pump** | Turn the pump on / off (reflects `pump_state`). |
| `number` | **Refill interval** | Days between refills (1–30). |
| `number` | **Max pump duration** | Max pump runtime in minutes (1–1439). |
| `time` | **Refill time** | Time of day the daily refill cycle runs. |
| `binary_sensor` × 10 | **Flags** | Water leakage, low battery, water tank low, draws air, slow recharge, high/low water usage, poor WiFi, poor ultrasonic signal, offline warning. |
| `sensor` (dynamic) | **Telemetry** | One sensor per time-series reported by the controller (water level, temperature, humidity, battery voltage, …). Known keys get proper units and device classes; unknown keys appear as generic numeric sensors. |
| `sensor` (diagnostic) | **Firmware** | Reported firmware version. |
| `button` × 7 | **Commands** | Restart device, ultrasonic clean loop, increase / decrease / read ultrasonic strength, reset WiFi credentials, update certificate. Disruptive commands are diagnostic and disabled by default. |

The polling interval is configurable (default **60 s**, range 30–3600 s).

## Installation

### Option 1 — HACS (recommended)

1. Open HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/mousaka20/boum-ha` with category **Integration**.
3. Search for **Boum** and install.
4. Restart Home Assistant.

### Option 2 — Manual

1. Copy the `custom_components/boum/` directory from this repo into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

After installation:

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Boum**.
3. Enter the email and password you use for the Boum app.

That's the entire setup. Home Assistant will:

- Validate your credentials by signing in to `https://api.boum.us`.
- Enumerate every controller claimed to your account.
- Create a device + entities per controller.

To change the polling interval later: **Settings → Devices & services → Boum → Configure**.

If your password ever changes, Home Assistant will prompt for re-authentication automatically.

## How it works

This is a thin async wrapper around the official synchronous [`boum` SDK](https://github.com/boum-garden/sdk). All blocking HTTP calls are dispatched to the executor with `hass.async_add_executor_job`, and a single long-lived SDK client per config entry handles automatic access-token refresh.

On every poll cycle (per device) the integration:

1. Lists claimed device IDs — so adding or removing devices from the Boum side propagates without an HA restart.
2. Fetches the device's reported + desired state and flags.
3. Fetches the last hour of telemetry and exposes the most recent value per series.

Write operations (switch toggles, number changes, command buttons) trigger a partial PATCH to the *desired* state — the SDK skips `None` fields, so we only ever send what changed.

## Project layout

```
boum-ha/
├── custom_components/boum/
│   ├── __init__.py          # async_setup_entry, unload, platform forwarding
│   ├── api.py               # Async wrapper around the sync SDK
│   ├── binary_sensor.py     # Device flags
│   ├── button.py            # Device commands
│   ├── config_flow.py       # User & re-auth flows, options flow
│   ├── const.py             # Domain, defaults, telemetry & flag mapping
│   ├── coordinator.py       # DataUpdateCoordinator
│   ├── entity.py            # Base entity with device-registry info
│   ├── manifest.json
│   ├── number.py            # refill_interval_days, max_pump_duration_minutes
│   ├── sensor.py            # firmware + dynamic telemetry
│   ├── strings.json
│   ├── switch.py            # pump
│   ├── time.py              # refill_time
│   └── translations/
│       └── en.json
├── .gitignore
├── hacs.json
├── info.md
├── LICENSE
└── README.md
```

## Compatibility

- Home Assistant **2024.6.0** or newer.
- Python 3.11+ (matches Home Assistant Core).
- `boum==1.4.0` (installed automatically by Home Assistant from PyPI on first setup).

## Known limitations & caveats

- **Telemetry key set is not fully documented.** The `/devices/{id}/data` endpoint returns whatever time-series the controller's firmware reports. `const.TELEMETRY_DEFINITIONS` annotates the keys we know about (water level, temperature, battery voltage, …). Unknown keys still appear as generic sensors — file an issue or PR if you see one we should add metadata for.
- **Flag semantics are inferred.** Each flag is an integer; we treat any non-zero value as "active." If your controller emits a value with a different meaning, file an issue.
- **Polling only.** The Boum API doesn't expose push / websocket events, so changes made in the Boum app may take up to one polling interval to appear in Home Assistant.
- **Diagnostic commands disabled by default.** `Reset WiFi credentials`, `Update certificate`, and the three ultrasonic-strength buttons are created disabled — enable them from the entity registry if you need them.

## Development

A quick syntax / import sanity check:

```bash
python -m py_compile custom_components/boum/*.py
```

This integration is independent of and not officially affiliated with Boum or Anthropic. The trademarks belong to their respective owners.

## License

[MIT](LICENSE)
