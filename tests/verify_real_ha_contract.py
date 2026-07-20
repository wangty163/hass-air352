from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

from custom_components.air352.const import DEVICE_TYPE_AIR, DOMAIN
from custom_components.air352.fan import Z120_PRODUCT_KEY
from custom_components.air352 import fan as fan_platform
from custom_components.air352 import select as select_platform
from custom_components.air352 import switch as switch_platform


class RealHomeAssistantContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.coordinator = SimpleNamespace(
            devices=[
                {
                    "iotId": "iot-1",
                    "productKey": Z120_PRODUCT_KEY,
                    "productName": "352 Z120",
                    "categoryKey": DEVICE_TYPE_AIR,
                }
            ],
            device_infos={
                "iot-1": {
                    "productKey": Z120_PRODUCT_KEY,
                    "firmwareVersion": "test-firmware",
                }
            },
            data={
                "iot-1": {
                    "PowerSwitch": {"value": 1},
                    "WorkMode": {"value": 4},
                    "WindSpeed": {"value": 1},
                }
            },
            api=SimpleNamespace(set_device_properties=AsyncMock()),
            async_set_updated_data=Mock(),
        )
        self.hass = SimpleNamespace(data={DOMAIN: {"entry-1": self.coordinator}})
        self.entry = SimpleNamespace(entry_id="entry-1")

    async def _setup(self, platform) -> list:
        entities = []
        await platform.async_setup_entry(
            self.hass,
            self.entry,
            lambda new_entities: entities.extend(new_entities),
        )
        return entities

    async def test_z120_exposes_three_active_control_contracts(self) -> None:
        fans = await self._setup(fan_platform)
        switches = await self._setup(switch_platform)
        selects = await self._setup(select_platform)

        power = next(
            entity
            for entity in switches
            if entity._attr_unique_id == "iot-1_PowerSwitch"
        )
        mode = next(
            entity
            for entity in selects
            if entity._attr_unique_id == "iot-1_WorkMode"
        )
        gear = next(
            entity
            for entity in selects
            if entity._attr_unique_id == "iot-1_WindSpeed"
        )

        self.assertTrue(power.is_on)
        self.assertEqual(mode.current_option, "manual")
        self.assertEqual(gear.current_option, "gear_1")
        self.assertEqual(
            mode.options,
            ["manual", "auto", "sleep", "skin", "air_drying"],
        )
        self.assertEqual(gear.options, [f"gear_{level}" for level in range(1, 7)])
        self.assertEqual(len(fans), 1)
        self.assertFalse(fans[0].entity_registry_enabled_default)

    async def test_split_actions_publish_independent_payloads(self) -> None:
        switches = await self._setup(switch_platform)
        selects = await self._setup(select_platform)
        power = next(
            entity
            for entity in switches
            if entity._attr_unique_id == "iot-1_PowerSwitch"
        )
        mode = next(
            entity
            for entity in selects
            if entity._attr_unique_id == "iot-1_WorkMode"
        )
        gear = next(
            entity
            for entity in selects
            if entity._attr_unique_id == "iot-1_WindSpeed"
        )

        await power.async_turn_off()
        await mode.async_select_option("sleep")
        await gear.async_select_option("gear_3")

        self.assertEqual(
            self.coordinator.api.set_device_properties.await_args_list,
            [
                call("iot-1", {"PowerSwitch": 0}),
                call("iot-1", {"WorkMode": 2}),
                call("iot-1", {"WindSpeed": 3, "WorkMode": 4}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
