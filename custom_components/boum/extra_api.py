"""Direct HTTP access for endpoints the official Boum Python SDK does not
expose, mirroring the capabilities of the official `boum` TypeScript CLI
(https://github.com/boum-garden/cli) but implemented purely in Python.

The SDK already handles sign-in, token storage, refresh-on-401 and the
``requests.Session`` lifecycle. We reuse all of that by holding a reference
to the SDK's ``ApiClient`` and calling through its session for the extra
endpoints. The only extra logic here is a tiny 401-retry decorator so that
a freshly-refreshed token is picked up automatically.

What's covered here (CLI parity, modelled per API.md in the CLI repo):

* ``GET  /devices/{id}/owner``                                — owner info
* ``GET  /devices/{id}``                                       — raw shadow,
  including fields ``DeviceStateModel.from_payload`` silently drops
  (``dailyRefill*``, ``refillTime{One,Two,Three}``, ``maxPubInterval``,
  ``hMaxPubInterval``, ``leakageDetection``, ``minFlowRate``).
* ``PATCH /devices/{id}`` ``state.desired`` writes for:
    - the three refill slots (enabled + time per slot),
    - the tuning fields above,
    - the ``resetLastPumped`` device command which the SDK's client-side
      allow-list rejects.
"""
from __future__ import annotations

from datetime import time as dt_time
import logging
from typing import Any
from urllib.parse import quote

import requests

from boum.api_client.v1.client import ApiClient

_LOGGER = logging.getLogger(__name__)

# Map slot number → (enable-flag API key, time API key). The CLI uses these
# exact keys and the API stores them in `state.{desired,reported}`.
REFILL_SLOT_KEYS: dict[int, tuple[str, str]] = {
    1: ("dailyRefill", "refillTimeOne"),
    2: ("dailyRefillTwo", "refillTimeTwo"),
    3: ("dailyRefillThree", "refillTimeThree"),
}

# Commands available via the API but **not** in the SDK's client-side
# DEVICE_COMMANDS allow-list. We have to send them via the raw PATCH path,
# because going through ``DeviceStateModel`` would trigger a ``ValueError``.
EXTRA_COMMANDS: tuple[str, ...] = ("resetLastPumped",)


class BoumExtraApiError(Exception):
    """Raised for any non-2xx response or transport-level failure."""


class BoumExtraApi:
    """Thin direct-API client built on top of the SDK's session.

    All methods are synchronous. The Home Assistant integration always wraps
    them in ``hass.async_add_executor_job``; we keep this class plain so it
    can also be reused from non-HA contexts (tests, scripts) the same way
    the official CLI is used.
    """

    def __init__(self, sdk_client: ApiClient) -> None:
        self._sdk = sdk_client

    # ------------------------------------------------------------------ HTTP

    @property
    def _session(self) -> requests.Session:
        # The SDK exposes its session as a public attribute on the root
        # endpoint. We deliberately do **not** create a parallel session —
        # using the SDK's keeps the Authorization header in sync with any
        # token refresh it performs internally.
        session = self._sdk.root.session
        if session is None:
            raise BoumExtraApiError(
                "SDK client is not connected; call ApiClient.connect() first"
            )
        return session

    @property
    def _base_url(self) -> str:
        # ``self._sdk.root.url`` is the fully-qualified v1 base — we just
        # reuse it to stay aligned with whichever environment the SDK was
        # configured for (prod / dev / local).
        return self._sdk.root.url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a request, transparently refreshing the access token on 401.

        Returns the unwrapped ``data`` field of the API envelope, or ``None``
        for responses with no body.
        """
        url = f"{self._base_url}{path}"

        def _do() -> requests.Response:
            return self._session.request(method, url, params=params, json=json)

        try:
            resp = _do()
        except requests.RequestException as err:
            raise BoumExtraApiError(f"transport error: {err}") from err

        if resp.status_code == 401 and self._looks_like_expired_token(resp):
            _LOGGER.debug("Boum access token expired; refreshing and retrying")
            try:
                # Re-use the SDK's refresh logic so the new token ends up on
                # the shared session header automatically.
                self._sdk._refresh_access_token()  # noqa: SLF001 — intentional
            except Exception as err:  # noqa: BLE001
                raise BoumExtraApiError(f"token refresh failed: {err}") from err
            try:
                resp = _do()
            except requests.RequestException as err:
                raise BoumExtraApiError(f"transport error after refresh: {err}") from err

        if not resp.ok:
            message = self._extract_error_message(resp)
            raise BoumExtraApiError(
                f"{method} {path} → HTTP {resp.status_code}: {message}"
            )

        if not resp.content:
            return None
        try:
            payload = resp.json()
        except ValueError as err:
            raise BoumExtraApiError(f"non-JSON response from {path}") from err
        # The API wraps successful payloads as ``{"data": ...}``. If the key
        # is missing we return the body verbatim so future endpoints aren't
        # locked out.
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    @staticmethod
    def _looks_like_expired_token(resp: requests.Response) -> bool:
        try:
            return "expired" in (resp.json().get("message") or "").lower()
        except ValueError:
            return False

    @staticmethod
    def _extract_error_message(resp: requests.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return resp.text or "<no body>"
        if isinstance(body, dict) and "message" in body:
            return str(body["message"])
        return str(body)

    # ----------------------------------------------------------- read paths

    def get_device_owner(self, device_id: str) -> Any:
        """``GET /devices/{id}/owner`` — CLI ``boum devices owner``."""
        return self._request("GET", f"/devices/{quote(device_id, safe='')}/owner")

    def get_device_shadow(self, device_id: str) -> dict[str, Any]:
        """``GET /devices/{id}`` returning the raw API payload.

        The SDK's ``Device.get_device()`` parses the response through
        ``DeviceStateModel`` and drops any field it doesn't model. We need
        ``dailyRefill*`` / ``refillTime{One,Two,Three}`` / tuning fields, so
        we fetch the raw dict directly. Shape::

            { "state": { "desired": {...}, "reported": {...} }, "flags": {...} }
        """
        data = self._request("GET", f"/devices/{quote(device_id, safe='')}")
        if not isinstance(data, dict):
            raise BoumExtraApiError("device endpoint returned a non-object payload")
        return data

    # -------------------------------------------------------- write helpers

    def patch_desired(self, device_id: str, desired: dict[str, Any]) -> None:
        """Send a partial ``state.desired`` PATCH. Empty payloads are a no-op."""
        if not desired:
            return
        self._request(
            "PATCH",
            f"/devices/{quote(device_id, safe='')}",
            json={"state": {"desired": desired}},
        )

    def set_refill_slot(
        self,
        device_id: str,
        slot: int,
        *,
        enabled: bool | None = None,
        refill_time: dt_time | None = None,
    ) -> None:
        """Enable/disable a refill slot or change its time.

        Maps to ``boum devices refill [deviceId] --slot {1|2|3}``.

        Slot indices are 1-based to match the CLI's user-facing argument.
        Either or both of ``enabled`` / ``refill_time`` may be set.
        """
        if slot not in REFILL_SLOT_KEYS:
            raise ValueError(f"slot must be 1, 2 or 3, got {slot!r}")
        if enabled is None and refill_time is None:
            return  # mirror the CLI's "needs at least one" rule by no-op'ing
        enabled_key, time_key = REFILL_SLOT_KEYS[slot]
        desired: dict[str, Any] = {}
        if enabled is not None:
            desired[enabled_key] = "on" if enabled else "off"
        if refill_time is not None:
            desired[time_key] = refill_time.strftime("%H:%M")
        self.patch_desired(device_id, desired)

    def tune(
        self,
        device_id: str,
        *,
        max_pub_interval_seconds: int | None = None,
        h_max_pub_interval_seconds: int | None = None,
        leakage_detection: bool | None = None,
        min_flow_rate: float | None = None,
    ) -> None:
        """Tuning fields not modelled by the Python SDK.

        Maps to the ``--max-pub-interval`` / ``--h-max-pub-interval`` /
        ``--leakage-detection`` / ``--min-flow-rate`` options of
        ``boum devices tune``.

        ``maxPumpDuration`` and ``refillInterval`` are intentionally **not**
        included here — they're already modelled by the SDK and exposed via
        the integration's existing ``Number`` entities, so duplicating them
        would invite drift.
        """
        desired: dict[str, Any] = {}
        if max_pub_interval_seconds is not None:
            if max_pub_interval_seconds <= 0:
                raise ValueError("max_pub_interval_seconds must be positive")
            desired["maxPubInterval"] = f"{int(max_pub_interval_seconds)}s"
        if h_max_pub_interval_seconds is not None:
            if h_max_pub_interval_seconds <= 0:
                raise ValueError("h_max_pub_interval_seconds must be positive")
            desired["hMaxPubInterval"] = f"{int(h_max_pub_interval_seconds)}s"
        if leakage_detection is not None:
            desired["leakageDetection"] = "on" if leakage_detection else "off"
        if min_flow_rate is not None:
            desired["minFlowRate"] = float(min_flow_rate)
        self.patch_desired(device_id, desired)

    def send_extra_command(self, device_id: str, command: str) -> None:
        """Send a command the SDK's allow-list rejects, e.g. ``resetLastPumped``."""
        if command not in EXTRA_COMMANDS:
            raise ValueError(
                f"{command!r} is not in the extra-commands allow-list "
                f"({EXTRA_COMMANDS!r}); use the SDK for standard commands"
            )
        self.patch_desired(device_id, {"deviceCommands": [command]})

    # ------------------------------------------------- shadow field parsers

    @staticmethod
    def parse_desired(shadow: dict[str, Any]) -> dict[str, Any]:
        """Pull out ``state.desired`` from a raw device shadow, defensively."""
        state = shadow.get("state") or {}
        return state.get("desired") or {}

    @staticmethod
    def parse_reported(shadow: dict[str, Any]) -> dict[str, Any]:
        """Pull out ``state.reported`` from a raw device shadow, defensively."""
        state = shadow.get("state") or {}
        return state.get("reported") or {}

    @staticmethod
    def parse_refill_slot(
        section: dict[str, Any], slot: int
    ) -> tuple[bool | None, dt_time | None]:
        """Decode a slot's ``(enabled, time)`` from a desired/reported dict.

        Returns ``(None, None)`` for slots that aren't in the payload, so
        callers can distinguish "not configured" from "explicitly off".
        """
        if slot not in REFILL_SLOT_KEYS:
            raise ValueError(f"slot must be 1, 2 or 3, got {slot!r}")
        enabled_key, time_key = REFILL_SLOT_KEYS[slot]

        enabled_raw = section.get(enabled_key)
        enabled: bool | None
        if enabled_raw == "on":
            enabled = True
        elif enabled_raw == "off":
            enabled = False
        else:
            enabled = None

        time_raw = section.get(time_key)
        parsed_time: dt_time | None = None
        if isinstance(time_raw, str) and ":" in time_raw:
            try:
                hh, mm = time_raw.split(":", 1)
                parsed_time = dt_time(int(hh), int(mm))
            except (TypeError, ValueError):
                parsed_time = None

        return enabled, parsed_time

    @staticmethod
    def parse_duration_seconds(section: dict[str, Any], key: str) -> int | None:
        """Parse a Boum-style ``"<n>s"`` duration. Returns int seconds or None."""
        raw = section.get(key)
        if not isinstance(raw, str) or not raw.endswith("s"):
            return None
        try:
            return int(raw[:-1])
        except ValueError:
            return None

    @staticmethod
    def parse_on_off(section: dict[str, Any], key: str) -> bool | None:
        raw = section.get(key)
        if raw == "on":
            return True
        if raw == "off":
            return False
        return None

    @staticmethod
    def parse_number(section: dict[str, Any], key: str) -> float | None:
        raw = section.get(key)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError:
                return None
        return None
