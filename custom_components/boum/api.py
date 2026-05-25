"""Async wrapper around the synchronous `boum` Python SDK.

The official SDK uses `requests` and is fully synchronous. Home Assistant's
event loop must never block, so every method here delegates to a thread via
`async_add_executor_job`. The SDK is also stateful — it manages an HTTP
session and access/refresh tokens internally — so we keep one long-lived
client per config entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from boum.api_client.v1.client import ApiClient
from boum.api_client.v1.models import DeviceFlagsModel, DeviceStateModel
from boum.resources.device import Device

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class BoumAuthError(Exception):
    """Raised when authentication fails (bad credentials, revoked token, etc.)."""


class BoumConnectionError(Exception):
    """Raised when the Boum API can't be reached or returns a transport error."""


@dataclass
class BoumDeviceSnapshot:
    """A snapshot of a single device taken on one poll cycle.

    Held as plain data so the coordinator can pass it around to entities
    without exposing the SDK's model classes directly.
    """

    device_id: str
    reported_state: DeviceStateModel | None
    desired_state: DeviceStateModel | None
    flags: DeviceFlagsModel | None
    # Latest value per telemetry key, e.g. {"temperature": 21.4, ...}.
    telemetry_latest: dict[str, float | None]
    # When that latest value was sampled, per key. Useful for "last_changed".
    telemetry_timestamps: dict[str, datetime]


class BoumClient:
    """Async-friendly facade over a single boum.ApiClient.

    Lifecycle:
      * Call ``async_connect()`` once on integration setup.
      * Call methods freely from any HA coroutine — they're scheduled on the
        executor.
      * Call ``async_close()`` on unload to release the HTTP session.

    The SDK transparently refreshes its access token on 401 responses, so we
    don't need to manage that here.
    """

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        self._hass = hass
        self._email = email
        self._password = password
        # The underlying SDK client. Lazily built in `_connect()` so the
        # constructor itself is cheap and safe to call from the event loop.
        self._client: ApiClient | None = None

    # -- connection management -----------------------------------------------

    def _connect(self) -> None:
        """Blocking: build the SDK client and sign in. Run in executor."""
        client = ApiClient(email=self._email, password=self._password)
        try:
            client.connect()
        except Exception as err:
            # The SDK doesn't expose a typed auth-error class, so we sniff the
            # error and normalise. Most 401s bubble up as HTTPError from
            # `response.raise_for_status()`.
            message = str(err).lower()
            if "401" in message or "unauthor" in message or "expired" in message:
                raise BoumAuthError(str(err)) from err
            raise BoumConnectionError(str(err)) from err
        self._client = client

    async def async_connect(self) -> None:
        await self._hass.async_add_executor_job(self._connect)

    def _close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:  # noqa: BLE001 — best-effort shutdown
                _LOGGER.debug("Error while disconnecting Boum client", exc_info=True)
            self._client = None

    async def async_close(self) -> None:
        await self._hass.async_add_executor_job(self._close)

    # -- device queries ------------------------------------------------------

    def _list_claimed_device_ids(self) -> list[str]:
        assert self._client is not None
        return Device.get_claimed_device_ids(self._client)

    async def async_list_claimed_device_ids(self) -> list[str]:
        return await self._hass.async_add_executor_job(self._list_claimed_device_ids)

    def _fetch_snapshot(
        self, device_id: str, lookback: timedelta
    ) -> BoumDeviceSnapshot:
        assert self._client is not None
        device = Device(device_id, self._client)
        model = device.get_device()

        # Telemetry can be expensive. We tolerate failures here — the device
        # state is still useful on its own.
        telemetry_latest: dict[str, float | None] = {}
        telemetry_timestamps: dict[str, datetime] = {}
        try:
            now = datetime.utcnow()
            data = device.get_telemetry_data(start=now - lookback, end=now)
            timestamps: list[datetime] = data.get("timestamp", []) or []
            for key, values in data.items():
                if key in ("deviceId", "timestamp"):
                    continue
                # Pick the most recent non-None reading.
                for value, ts in zip(reversed(values), reversed(timestamps)):
                    if value is not None:
                        telemetry_latest[key] = value
                        telemetry_timestamps[key] = ts
                        break
                else:
                    telemetry_latest[key] = None
        except Exception:  # noqa: BLE001 — telemetry is opportunistic
            _LOGGER.debug(
                "Failed to fetch telemetry for %s; continuing with state only",
                device_id,
                exc_info=True,
            )

        return BoumDeviceSnapshot(
            device_id=device_id,
            reported_state=model.reported_state,
            desired_state=model.desired_state,
            flags=model.flags,
            telemetry_latest=telemetry_latest,
            telemetry_timestamps=telemetry_timestamps,
        )

    async def async_fetch_snapshot(
        self, device_id: str, lookback: timedelta
    ) -> BoumDeviceSnapshot:
        try:
            return await self._hass.async_add_executor_job(
                self._fetch_snapshot, device_id, lookback
            )
        except Exception as err:
            raise BoumConnectionError(str(err)) from err

    # -- write operations ----------------------------------------------------

    def _patch_desired_state(self, device_id: str, **fields: Any) -> None:
        """Send a partial desired-state update.

        Only the fields explicitly passed in are sent — the SDK's
        DeviceStateModel.to_payload() skips None values, so this gives a
        proper PATCH semantic.
        """
        assert self._client is not None
        desired = DeviceStateModel(**fields)
        Device(device_id, self._client).set_desired_device_state(desired)

    async def async_patch_desired_state(self, device_id: str, **fields: Any) -> None:
        try:
            await self._hass.async_add_executor_job(
                lambda: self._patch_desired_state(device_id, **fields)
            )
        except Exception as err:
            raise BoumConnectionError(str(err)) from err

    def _send_command(self, device_id: str, command: str) -> None:
        assert self._client is not None
        Device(device_id, self._client).send_device_command(command)

    async def async_send_command(self, device_id: str, command: str) -> None:
        try:
            await self._hass.async_add_executor_job(
                self._send_command, device_id, command
            )
        except Exception as err:
            raise BoumConnectionError(str(err)) from err
