import asyncio
import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import Air352ApiClient, Air352AuthError, Air352ConnectionError, Air352ApiError
from .const import (
    ACTIVE_PROPERTY_REFRESH_INTERVAL,
    ACTIVE_PROPERTY_REFRESH_SETTLE_SECONDS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    Z120_PRODUCT_KEY,
)
from .mobile_channel import Air352MobileChannel
from .state import PropertyState

_LOGGER = logging.getLogger(__name__)


class Air352Coordinator(DataUpdateCoordinator):

    def __init__(
        self,
        hass: HomeAssistant,
        api: Air352ApiClient,
        username: str,
    ) -> None:
        super().__init__(
            hass, _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self._username = username
        self.devices: list[dict] = []
        self.device_infos: dict[str, dict] = {}
        self._property_state = PropertyState()
        self._mobile_channel: Air352MobileChannel | None = None
        self._last_active_refresh: dict[str, float] = {}
        self._monotonic = time.monotonic

    async def async_setup(self) -> None:
        try:
            await self.api.authenticate()
            self.devices = await self.api.get_device_list()
            tasks = [self.api.get_device_info(d["iotId"]) for d in self.devices]
            infos = await asyncio.gather(*tasks, return_exceptions=True)
            for dev, info in zip(self.devices, infos):
                if isinstance(info, dict):
                    self.device_infos[dev["iotId"]] = info
        except Air352AuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except (Air352ConnectionError, Air352ApiError) as e:
            raise UpdateFailed(str(e)) from e

    async def async_start_push(self) -> None:
        """Start the same account-bound push channel used by the official App."""
        channel = Air352MobileChannel(
            self.hass,
            self.api,
            self._username,
            self._async_handle_mobile_message,
            self._async_handle_mobile_state,
        )
        self._mobile_channel = channel
        try:
            await channel.async_start()
        except Exception:
            _LOGGER.exception(
                "Failed to start 352 official-app push channel; "
                "REST polling remains active"
            )

    async def async_shutdown(self) -> None:
        """Stop background network resources."""
        if self._mobile_channel is not None:
            await self._mobile_channel.async_stop()
            self._mobile_channel = None

    async def async_set_device_properties(
        self,
        iot_id: str,
        values: dict[str, int],
        *,
        optimistic_values: dict[str, int] | None = None,
    ) -> None:
        """Optimistically send a command and hold it until device confirmation."""
        optimistic = optimistic_values or values
        token = self._property_state.begin_command(iot_id, optimistic)
        self.async_set_updated_data(self._property_state.snapshot())
        try:
            await self.api.set_device_properties(iot_id, values)
        except Exception:
            self._property_state.rollback_command(token)
            self.async_set_updated_data(self._property_state.snapshot())
            raise

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            await self._async_request_active_reports()
            tasks = [self.api.get_device_properties(d["iotId"]) for d in self.devices]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Air352AuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except (Air352ConnectionError, Air352ApiError) as e:
            raise UpdateFailed(str(e)) from e

        for dev, result in zip(self.devices, results):
            iot_id = dev["iotId"]
            if isinstance(result, Exception):
                _LOGGER.warning("Failed to get properties for %s: %s", iot_id, result)
                self._property_state.data.setdefault(iot_id, {})
            else:
                self._property_state.merge_device(
                    iot_id,
                    result,
                    source="rest",
                )
        return self._property_state.snapshot()

    async def _async_request_active_reports(self) -> None:
        """Periodically trigger the Z120 full report used by the official App."""
        now = self._monotonic()
        due_devices = []
        for device in self.devices:
            if device.get("productKey") != Z120_PRODUCT_KEY:
                continue
            iot_id = device["iotId"]
            last_refresh = self._last_active_refresh.get(iot_id)
            if (
                last_refresh is not None
                and now - last_refresh < ACTIVE_PROPERTY_REFRESH_INTERVAL
            ):
                continue
            # Record the attempt before sending so a failing cloud command does
            # not turn the normal 10-second reconciliation into a retry storm.
            self._last_active_refresh[iot_id] = now
            due_devices.append(iot_id)

        if not due_devices:
            return

        results = await asyncio.gather(
            *(
                self.api.request_z120_property_report(iot_id)
                for iot_id in due_devices
            ),
            return_exceptions=True,
        )
        report_requested = False
        for iot_id, result in zip(due_devices, results):
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Failed to request active Z120 property report for %s: %s; "
                    "using the latest cloud snapshot",
                    iot_id,
                    result,
                )
            else:
                report_requested = True

        if report_requested:
            await asyncio.sleep(ACTIVE_PROPERTY_REFRESH_SETTLE_SECONDS)

    async def _async_handle_mobile_message(
        self,
        path: str,
        payload: dict,
    ) -> None:
        """Apply an official mobile-channel downstream message."""
        if path == "thing/properties":
            params = payload.get("params", {})
            iot_id = params.get("iotId")
            items = params.get("items")
            if (
                isinstance(iot_id, str)
                and isinstance(items, dict)
                and any(device.get("iotId") == iot_id for device in self.devices)
            ):
                if self._property_state.merge_device(
                    iot_id,
                    items,
                    source="push",
                ):
                    self.async_set_updated_data(
                        self._property_state.snapshot()
                    )
            return

        if path in {"thing/status", "thing/events"}:
            await self.async_request_refresh()

    async def _async_handle_mobile_state(self, connected: bool) -> None:
        """Reconcile missed changes whenever the push connection changes."""
        if connected:
            _LOGGER.debug("352 push channel bound; reconciling full state")
        else:
            _LOGGER.warning(
                "352 push channel unavailable; using REST polling"
            )
        await self.async_request_refresh()
