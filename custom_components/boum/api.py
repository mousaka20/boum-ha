"""Async wrapper around the synchronous `boum` Python SDK.

The official SDK uses `requests` and is fully synchronous. Home Assistant's
event loop must never block, so every method here delegates to a thread via
`async_add_executor_job`. The SDK is also stateful — it manages an HTTP
session and access/refresh tokens internally — so we keep one long-lived
client per config entry.

For endpoints the SDK doesn't model (refill slots, additional tuning fields,
the ``resetLastPumped`` command, the ``/owner`` endpoint) we delegate to
``BoumExtraApi``, a small direct-HTTP client that piggybacks on the SDK's
authenticated session. This mirrors the surface of the official Boum CLI
(https://github.com/boum-garden/cli) without requiring Node.js.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
import logging
from typing import Any

from boum.api_client.v1.client import ApiClient
from boum.api_client.v1.models import DeviceFlagsModel, DeviceStateModel
from boum.resources.device import Device

from homeassistant.core import HomeAssistant

from .extra_api import BoumExtraApi, BoumExtraApiError

_LOGGER = logging.getLogger(__name__)


class BoumAuthError(Exception):
    """Raised when authentication fails (bad credentials, revoked token, etc.)."""


class BoumConnectionError(Exception):
    """Raised when the Boum API can't be reached or returns a transport error."""


@dataclass
class BoumDeviceSnapshot:
    """A snapshot of a single device taken on one poll cycle.

    Held as plain data so the coordinator can pass it around to entities
    without exposing the SDK's model classes directly. ``raw_reported`` and
    ``raw_desired`` carry the full state shadow including fields the SDK's
    ``DeviceStateModel`` silently drops (refill slots, ``maxPubInterval``,
    ``leakageDetection``, ``minFlowRate``, etc.).
    """

    device_id: str
    reported_state: DeviceStateModel | None
    desired_state: DeviceStateModel | None
    flags: DeviceFlagsModel | None
    telemetry_latest: dict[str, float | None]
    telemetry_timestamps: dict[str, datetime]
    raw_reported: dict[str, Any] = field(default_factory=dict)
    raw_desired: dict[str, Any] = field(default_factory=dict)
    # Filled lazily on first refresh and not re-polled — owner doesn't change
    # mid-session in any meaningful way.
    owner: dict[str, Any] | None = None


class BoumClient:
    """Async-friendly facade over a single boum.ApiClient + BoumExtraApi.

    Lifecycle:
      * Call ``async_connect()`` once on integration setup.
      * Call methods freely from any HA coroutine — they're scheduled on the
        executor.
      * Call ``async_close()`` on unload to release the HTTP session.

    The SDK transparently refreshes its access token on 401 responses, and
    ``BoumExtraApi`` re-uses the same refresh logic for its raw calls.
    """

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        self._hass = hass
        self._email = email
        self._password = password
        self._client: ApiClient | None = None
        self._extra: BoumExtraApi | None = None
        # device_id -> owner dict; cached for the lifetime of the client so
        # we only hit /owner once per device.
        self._owner_cache: dict[str, dict[str, Any]] = {}

    # -- connection management -----------------------------------------------

    def _connect(self) -> None:
        """Blocking: build the SDK client and sign in. Run in executor."""
        client = ApiClient(email=self._email, password=self._password)
        try:
            client.connect()
        except Exception as err:
            message = str(err).lower()
            if "401" in message or "unauthor" in message or "expired" in message:
                raise BoumAuthError(str(err)) from err
            raise BoumConnectionError(str(err)) from err
        self._client = client
        self._extra = BoumExtraApi(client)

    async def async_connect(self) -> None:
        await self._hass.async_add_executor_job(self._connect)

    def _close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:  # noqa: BLE001 — best-effort shutdown
                _LOGGER.debug("Error while disconnecting Boum client", exc_info=True)
            self._client = None
            self._extra = None
            self._owner_cache.clear()

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
        assert self._extra is not None

        device = Device(device_id, self._client)
        model = device.get_device()

        # Also fetch the raw shadow so we can read fields the SDK drops.
        raw_reported: dict[str, Any] = {}
        raw_desired: dict[str, Any] = {}
        try:
            shadow = self._extra.get_device_shadow(device_id)
            raw_reported = self._extra.parse_reported(shadow)
            raw_desired = self._extra.parse_desired(shadow)
        except BoumExtraApiError:
            _LOGGER.debug(
                "Couldn't fetch raw shadow for %s; slot/tuning entities will be unavailable",
                device_id,
                exc_info=True,
            )

        # Owner: fetched once per device, then cached.
        owner = self._owner_cache.get(device_id)
        if owner is None:
            try:
                fetched = self._extra.get_device_owner(device_id)
                if isinstance(fetched, dict):
                    owner = fetched
                    self._owner_cache[device_id] = owner
            except BoumExtraApiError:
                _LOGGER.debug(
                    "Couldn't fetch owner for %s", device_id, exc_info=True
                )

        # Telemetry — opportunistic.
        telemetry_latest: dict[str, float | None] = {}
        telemetry_timestamps: dict[str, datetime] = {}
        try:
            now = datetime.utcnow()
            data = device.get_telemetry_data(start=now - lookback, end=now)
            timestamps: list[datetime] = data.get("timestamp", []) or []
            for key, values in data.items():
                if key in ("deviceId", "timestamp"):
                    continue
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
            raw_reported=raw_reported,
            raw_desired=raw_desired,
            owner=owner,
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

    # -- write operations: SDK-modelled fields -------------------------------

    def _patch_desired_state(self, device_id: str, **fields: Any) -> None:
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

    # -- write operations: CLI-only fields (via raw HTTP) --------------------

    async def async_set_refill_slot(
        self,
        device_id: str,
        slot: int,
        *,
        enabled: bool | None = None,
        refill_time: dt_time | None = None,
    ) -> None:
        assert self._extra is not None
        try:
            await self._hass.async_add_executor_job(
                lambda: self._extra.set_refill_slot(  # type: ignore[union-attr]
                    device_id, slot, enabled=enabled, refill_time=refill_time
                )
            )
        except BoumExtraApiError as err:
            raise BoumConnectionError(str(err)) from err

    async def async_tune(
        self,
        device_id: str,
        *,
        max_pub_interval_seconds: int | None = None,
        h_max_pub_interval_seconds: int | None = None,
        leakage_detection: bool | None = None,
        min_flow_rate: float | None = None,
    ) -> None:
        assert self._extra is not None
        try:
            await self._hass.async_add_executor_job(
                lambda: self._extra.tune(  # type: ignore[union-attr]
                    device_id,
                    max_pub_interval_seconds=max_pub_interval_seconds,
                    h_max_pub_interval_seconds=h_max_pub_interval_seconds,
                    leakage_detection=leakage_detection,
                    min_flow_rate=min_flow_rate,
                )
            )
        except BoumExtraApiError as err:
            raise BoumConnectionError(str(err)) from err

    async def async_send_extra_command(self, device_id: str, command: str) -> None:
        """Send a command rejected by the SDK's allow-list (e.g. ``resetLastPumped``)."""
        assert self._extra is not None
        try:
            await self._hass.async_add_executor_job(
                lambda: self._extra.send_extra_command(  # type: ignore[union-attr]
                    device_id, command
                )
            )
        except BoumExtraApiError as err:
            raise BoumConnectionError(str(err)) from err
