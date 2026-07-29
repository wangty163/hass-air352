"""Timestamp-aware property reconciliation for 352 cloud state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Any
import uuid


COMMAND_CONFIRM_TIMEOUT = 15.0
CONFIRM_CLOCK_SKEW_MS = 3_000
_MISSING = object()


@dataclass
class PendingProperty:
    """One optimistic property waiting for device confirmation."""

    token: str
    target: Any
    issued_at_ms: int
    expires_at: float
    previous: Any


class PropertyState:
    """Merge REST snapshots, mobile pushes, and optimistic commands safely."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self._pending: dict[tuple[str, str], PendingProperty] = {}

    def begin_command(
        self,
        iot_id: str,
        values: dict[str, Any],
        *,
        now_ms: int | None = None,
        monotonic_now: float | None = None,
    ) -> str:
        """Apply optimistic values and return a rollback token."""
        issued_at_ms = now_ms or int(time.time() * 1000)
        expires_at = (
            monotonic_now if monotonic_now is not None else time.monotonic()
        ) + COMMAND_CONFIRM_TIMEOUT
        token = uuid.uuid4().hex
        properties = self.data.setdefault(iot_id, {})

        for key, target in values.items():
            current_value = properties.get(key, _MISSING)
            previous = (
                _MISSING
                if current_value is _MISSING
                else deepcopy(current_value)
            )
            self._pending[(iot_id, key)] = PendingProperty(
                token=token,
                target=target,
                issued_at_ms=issued_at_ms,
                expires_at=expires_at,
                previous=previous,
            )
            current = properties.get(key)
            if isinstance(current, dict):
                optimistic = dict(current)
                optimistic["value"] = target
                optimistic["time"] = issued_at_ms
            else:
                optimistic = {"value": target, "time": issued_at_ms}
            properties[key] = optimistic

        return token

    def rollback_command(self, token: str) -> None:
        """Rollback still-pending properties from a failed cloud command."""
        for pending_key, pending in list(self._pending.items()):
            if pending.token != token:
                continue
            iot_id, property_key = pending_key
            properties = self.data.setdefault(iot_id, {})
            if pending.previous is _MISSING:
                properties.pop(property_key, None)
            else:
                properties[property_key] = pending.previous
            self._pending.pop(pending_key, None)

    def merge_device(
        self,
        iot_id: str,
        incoming: dict[str, Any],
        *,
        source: str,
        monotonic_now: float | None = None,
    ) -> bool:
        """Merge one REST or push property set, returning whether state changed."""
        now = monotonic_now if monotonic_now is not None else time.monotonic()
        properties = self.data.setdefault(iot_id, {})
        changed = False

        for key, raw_property in incoming.items():
            incoming_property = (
                dict(raw_property)
                if isinstance(raw_property, dict)
                else {"value": raw_property}
            )
            incoming_value = incoming_property.get("value")
            incoming_time = _property_time(incoming_property)
            pending_key = (iot_id, key)
            pending = self._pending.get(pending_key)
            expired_pending = pending is not None and now >= pending.expires_at

            if pending is not None and not expired_pending:
                if incoming_value != pending.target:
                    continue
                if (
                    incoming_time is not None
                    and incoming_time
                    < pending.issued_at_ms - CONFIRM_CLOCK_SKEW_MS
                ):
                    continue
                self._pending.pop(pending_key, None)
            elif expired_pending:
                self._pending.pop(pending_key, None)

            current = properties.get(key)
            current_time = _property_time(current)
            if (
                not expired_pending
                and incoming_time is not None
                and current_time is not None
                and incoming_time < current_time
            ):
                continue

            if current != incoming_property:
                properties[key] = incoming_property
                changed = True

        return changed

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a shallow top-level snapshot suitable for a coordinator."""
        return dict(self.data)


def _property_time(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    timestamp = value.get("time")
    if isinstance(timestamp, bool):
        return None
    if isinstance(timestamp, (int, float)):
        return int(timestamp)
    if isinstance(timestamp, str):
        try:
            return int(timestamp)
        except ValueError:
            return None
    return None
