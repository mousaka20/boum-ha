# Boum for Home Assistant

Integrates the [Boum](https://boum.garden/) smart solar irrigation system into Home Assistant.

After install, add the integration from **Settings → Devices & services → Add integration → Boum** and sign in with your Boum account credentials.

Each claimed controller becomes a device with:

- A **pump** switch
- **Refill interval**, **max pump duration** and **refill time** controls
- **Binary sensors** for every device flag (water leakage, low battery, water level, WiFi quality, …)
- **Telemetry sensors** for every time-series the controller reports (water level, temperature, battery voltage, …)
- **Command buttons** (restart, ultrasonic clean loop, …)

See the [README](https://github.com/mousaka20/boum-ha) for full details.
