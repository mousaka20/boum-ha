# Boum for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) custom integration for the [Boum](https://boum.garden/) smart solar-powered plant irrigation system, built on top of the official [`boum` Python SDK](https://github.com/boum-garden/sdk).

> Boum is a Swiss smart irrigation system: a solar-powered controller pumps water from a tank into self-watering pots equipped with capillary wicks. The controller is cloud-connected, exposes telemetry (water level, climate, battery, ...), and can be configured via the Boum app — and now from Home Assistant.

## Features

For every Boum controller claimed to your account this integration creates:

| Platform | Entity | Source | Description |
| --- | --- | --- | --- |
| `switch` | **Pump** | SDK | Turn the pump on / off (reflects `pump_state`). |
| `switch` × 3 | **Refill slot 1/2/3** | CLI-only | Enable each of the controller's three daily refill slots. |
| `switch` | **Leakage detection** | CLI-only | Toggle leak detection (`leakageDetection`). |
| `number` | **Refill interval** | SDK | Days between refills (1–30). |
| `number` | **Max pump duration** | SDK | Max pump runtime in minutes (1–1439). |
| `number` | **Max publication interval (low/high battery)** | CLI-only | `maxPubInterval` / `hMaxPubInterval` in seconds. |
| `number` | **Minimum flow rate** | CLI-only | `minFlowRate`, used by leak detection. |
| `time` × 3 | **Refill slot 1/2/3 time** | CLI-only | Time-of-day per refill slot (`refillTimeOne/Two/Three`). |
| `time` | **Refill time (legacy)** | SDK | The pre-slot single-refill field (`refillTime`); disabled by default. |
| `binary_sensor` × 10 | **Flags** | SDK | Water leakage, low battery, water tank low, draws air, slow recharge, high/low water usage, poor WiFi, poor ultrasonic signal, offline warning. |
| `sensor` (dynamic) | **Telemetry** | SDK | One sensor per time-series reported by the controller. Known keys get proper units and device classes. |
| `sensor` (diagnostic) | **Firmware** | SDK | Reported firmware version. |
| `sensor` (diagnostic) | **Owner** | CLI-only | Owner of the device (`GET /devices/{id}/owner`). Disabled by default. |
| `button` × 8 | **Commands** | SDK + CLI-only | Restart device, ultrasonic clean loop, ultrasonic strength inc/dec/read, reset WiFi credentials, update certificate, **reset last-pumped counter** (CLI-only). Disruptive commands are diagnostic and disabled by default. |

Entities backed by API fields the SDK doesn't model are marked **CLI-only**: those go through a small direct-HTTP client (`extra_api.py`) that piggybacks on the SDK's authenticated session, mirroring the surface of the [official Boum CLI](https://github.com/boum-garden/cli) but implemented entirely in Python — no Node.js required.

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

### CLI parity without Node.js

The official [`boum-garden/cli`](https://github.com/boum-garden/cli) (TypeScript) exposes several endpoints the Python SDK doesn't model: refill **slots** 1/2/3, the `leakageDetection` / `minFlowRate` / `maxPubInterval` / `hMaxPubInterval` tuning fields, the `resetLastPumped` command, and the `GET /devices/{id}/owner` endpoint.

To bring those into Home Assistant without shelling out to Node, this integration includes a small pure-Python module — `extra_api.py` — that talks directly to the REST API for those endpoints. It piggybacks on the SDK's `requests.Session` so the `Authorization` header stays in sync, and it calls the SDK's `_refresh_access_token` on a 401 — re-using the SDK's auth machinery rather than re-implementing it.

The wire-level JSON it produces is identical to the curl recipes in the CLI repo's `API.md`; the unit tests in this repo cover that exactly.

### Per-poll workflow

On every poll cycle (per device) the integration:

1. Lists claimed device IDs — so adding or removing devices from the Boum side propagates without an HA restart.
2. Fetches the device's reported + desired state and flags via the SDK.
3. Fetches the raw shadow via `extra_api` so slot/tuning fields the SDK silently drops are still available to entities.
4. Fetches the owner (cached after the first call — owners don't change session-to-session).
5. Fetches the last hour of telemetry and exposes the most recent value per series.

Write operations (switch toggles, number changes, command buttons) trigger a partial PATCH to the *desired* state. SDK-modelled fields go through `DeviceStateModel`; CLI-only fields go through `extra_api.patch_desired` so we only ever send what changed.

## Project layout

```
boum-ha/
├── custom_components/boum/
│   ├── __init__.py          # async_setup_entry, unload, platform forwarding
│   ├── api.py               # Async wrapper around the sync SDK + extra_api
│   ├── extra_api.py         # Direct-HTTP client for CLI-only endpoints
│   ├── binary_sensor.py     # Device flags
│   ├── button.py            # Device commands (incl. resetLastPumped)
│   ├── config_flow.py       # User & re-auth flows, options flow
│   ├── const.py             # Domain, defaults, telemetry & flag mapping
│   ├── coordinator.py       # DataUpdateCoordinator
│   ├── entity.py            # Base entity with device-registry info
│   ├── manifest.json
│   ├── number.py            # interval, duration, pub-interval, flow-rate
│   ├── sensor.py            # firmware, owner, dynamic telemetry
│   ├── strings.json
│   ├── switch.py            # pump, refill slots, leakage detection
│   ├── time.py              # refill_time + 3 slot times
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
- **Slot / tuning fields are conditionally available.** Older firmwares may not emit `dailyRefillTwo`, `minFlowRate`, etc. The corresponding entities mark themselves *unavailable* when their key isn't present in the shadow, so they don't clutter your UI on devices that don't support them.
- **Flag semantics are inferred.** Each flag is an integer; we treat any non-zero value as "active." If your controller emits a value with a different meaning, file an issue.
- **Polling only.** The Boum API doesn't expose push / websocket events, so changes made in the Boum app may take up to one polling interval to appear in Home Assistant.
- **Diagnostic commands disabled by default.** `Reset WiFi credentials`, `Update certificate`, `Reset last-pumped counter`, and the three ultrasonic-strength buttons are created disabled — enable them from the entity registry if you need them.
- **`extra_api.py` uses one SDK-internal method.** It calls `ApiClient._refresh_access_token` to recover from 401s. If a future SDK release renames that, the integration's CLI-parity surface will warn in the logs and you'll need to update — the SDK-modelled surface keeps working regardless.

## Development

A quick syntax / import sanity check:

```bash
python -m py_compile custom_components/boum/*.py
```

This integration is independent of and not officially affiliated with Boum or Anthropic. The trademarks belong to their respective owners.

## License

[MIT](LICENSE)
