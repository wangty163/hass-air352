from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components"),
)

from air352.api import Air352ApiClient, Air352ApiError  # noqa: E402
from air352.const import (  # noqa: E402
    ACTIVE_PROPERTY_REFRESH_SETTLE_SECONDS,
    Z120_PRODUCT_KEY,
)
from air352.coordinator import Air352Coordinator  # noqa: E402
from air352.state import PropertyState  # noqa: E402


class ActiveRefreshApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_z120_report_uses_official_query_property(self) -> None:
        client = object.__new__(Air352ApiClient)
        client.set_device_properties = AsyncMock()

        await client.request_z120_property_report("iot-z120")

        client.set_device_properties.assert_awaited_once_with(
            "iot-z120",
            {"ResearchAllProperty": "1"},
        )


class ActiveRefreshCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def _coordinator(self, *, report_error: Exception | None = None):
        coordinator = object.__new__(Air352Coordinator)
        coordinator.devices = [
            {"iotId": "iot-z120", "productKey": Z120_PRODUCT_KEY},
            {"iotId": "iot-other", "productKey": "another-product"},
        ]
        coordinator.api = SimpleNamespace(
            request_z120_property_report=AsyncMock(side_effect=report_error),
            get_device_properties=AsyncMock(
                side_effect=[
                    {"PM25": {"value": 6, "time": 2_000}},
                    {"PM25": {"value": 9, "time": 2_000}},
                ]
            ),
        )
        coordinator._property_state = PropertyState()
        coordinator._last_active_refresh = {}
        coordinator._monotonic = Mock(return_value=100.0)
        return coordinator

    async def test_z120_is_triggered_before_snapshot_and_rate_limited(self) -> None:
        coordinator = self._coordinator()
        coordinator._monotonic.side_effect = [100.0, 120.0, 161.0]
        with patch(
            "air352.coordinator.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            first = await coordinator._async_update_data()
            self.assertEqual(first["iot-z120"]["PM25"]["value"], 6)
            coordinator.api.get_device_properties.side_effect = [
                {"PM25": {"value": 7, "time": 3_000}},
                {"PM25": {"value": 10, "time": 3_000}},
                {"PM25": {"value": 8, "time": 4_000}},
                {"PM25": {"value": 11, "time": 4_000}},
            ]
            await coordinator._async_update_data()
            await coordinator._async_update_data()

        self.assertEqual(
            coordinator.api.request_z120_property_report.await_count,
            2,
        )
        coordinator.api.request_z120_property_report.assert_awaited_with(
            "iot-z120"
        )
        self.assertEqual(sleep.await_count, 2)
        sleep.assert_awaited_with(ACTIVE_PROPERTY_REFRESH_SETTLE_SECONDS)

    async def test_trigger_failure_falls_back_to_cloud_snapshot(self) -> None:
        coordinator = self._coordinator(
            report_error=Air352ApiError(500, "query unavailable")
        )
        with patch(
            "air352.coordinator.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            data = await coordinator._async_update_data()

        self.assertEqual(data["iot-z120"]["PM25"]["value"], 6)
        sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
