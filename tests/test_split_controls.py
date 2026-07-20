from __future__ import annotations

import unittest

from control_test_support import (
    FakeCoordinator,
    HomeAssistantError,
    Z120_PRODUCT_KEY,
    entity_by_unique_id,
    load_platform_module,
    setup_entities,
)


MODE_OPTIONS = ["manual", "auto", "sleep", "skin", "air_drying"]
GEAR_OPTIONS = [f"gear_{level}" for level in range(1, 7)]


class Z120PowerSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.module = load_platform_module("switch")
        self.coordinator = FakeCoordinator(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 4},
                "WindSpeed": {"value": 1},
            }
        )
        entities = await setup_entities(self.module, self.coordinator)
        self.entity = entity_by_unique_id(entities, "iot-1_PowerSwitch")

    async def test_z120_gets_a_dedicated_power_switch(self) -> None:
        self.assertTrue(self.entity.is_on)
        self.assertEqual(self.entity._attr_translation_key, "powerswitch")

    async def test_power_action_only_writes_power(self) -> None:
        await self.entity.async_turn_off()

        self.coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"PowerSwitch": 0}
        )
        self.assertEqual(self.coordinator.data["iot-1"]["WorkMode"]["value"], 4)
        self.assertEqual(self.coordinator.data["iot-1"]["WindSpeed"]["value"], 1)
        self.assertFalse(self.entity.is_on)
        self.coordinator.async_set_updated_data.assert_called_once_with(
            self.coordinator.data
        )

    async def test_cloud_failure_does_not_change_optimistic_power_state(self) -> None:
        self.coordinator.api.set_device_properties.side_effect = RuntimeError(
            "cloud error"
        )

        with self.assertRaisesRegex(HomeAssistantError, "Failed to update") as raised:
            await self.entity.async_turn_off()

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertTrue(self.entity.is_on)
        self.coordinator.async_set_updated_data.assert_not_called()

    async def test_known_z120_power_exists_after_empty_first_snapshot(self) -> None:
        coordinator = FakeCoordinator({})
        entities = await setup_entities(self.module, coordinator)
        entity = entity_by_unique_id(entities, "iot-1_PowerSwitch")

        self.assertFalse(entity.available)
        self.assertIsNone(entity.is_on)

        coordinator.data["iot-1"]["PowerSwitch"] = {"value": 1}
        self.assertTrue(entity.available)
        self.assertTrue(entity.is_on)

    async def test_non_z120_air_purifier_does_not_get_duplicate_power(self) -> None:
        coordinator = FakeCoordinator(
            {"PowerSwitch": {"value": 1}}, product_key="legacy-product"
        )

        entities = await setup_entities(self.module, coordinator)

        self.assertFalse(
            any(entity._attr_unique_id == "iot-1_PowerSwitch" for entity in entities)
        )


class Z120SelectSetupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.module = load_platform_module("select")

    async def test_z120_creates_mode_and_manual_gear_selects(self) -> None:
        coordinator = FakeCoordinator(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 4},
                "WindSpeed": {"value": 2},
            }
        )

        entities = await setup_entities(self.module, coordinator)
        mode = entity_by_unique_id(entities, "iot-1_WorkMode")
        gear = entity_by_unique_id(entities, "iot-1_WindSpeed")

        self.assertEqual(mode.options, MODE_OPTIONS)
        self.assertEqual(gear.options, GEAR_OPTIONS)
        self.assertEqual(mode.current_option, "manual")
        self.assertEqual(gear.current_option, "gear_2")

    async def test_lowercase_windspeed_keeps_stable_unique_id(self) -> None:
        coordinator = FakeCoordinator(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 4},
                "windspeed": {"value": 3},
            }
        )

        entities = await setup_entities(self.module, coordinator)
        gear = entity_by_unique_id(entities, "iot-1_WindSpeed")

        self.assertEqual(gear.current_option, "gear_3")

    async def test_non_z120_does_not_get_split_selects(self) -> None:
        coordinator = FakeCoordinator(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 2},
                "WindSpeed": {"value": 2},
            },
            product_key="legacy-product",
        )

        self.assertEqual(await setup_entities(self.module, coordinator), [])

    async def test_empty_first_snapshot_registers_and_later_recovers(self) -> None:
        coordinator = FakeCoordinator({})

        entities = await setup_entities(self.module, coordinator)
        mode = entity_by_unique_id(entities, "iot-1_WorkMode")
        gear = entity_by_unique_id(entities, "iot-1_WindSpeed")

        self.assertFalse(mode.available)
        self.assertFalse(gear.available)
        self.assertIsNone(mode.current_option)
        self.assertIsNone(gear.current_option)

        coordinator.data["iot-1"].update(
            {"WorkMode": {"value": 4}, "WindSpeed": {"value": 2}}
        )
        self.assertTrue(mode.available)
        self.assertTrue(gear.available)
        self.assertEqual(mode.current_option, "manual")
        self.assertEqual(gear.current_option, "gear_2")


class Z120ModeSelectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.module = load_platform_module("select")
        self.coordinator = FakeCoordinator(
            {
                "PowerSwitch": {"value": 0},
                "WorkMode": {"value": 4},
                "WindSpeed": {"value": 2},
            }
        )
        entities = await setup_entities(self.module, self.coordinator)
        self.entity = entity_by_unique_id(entities, "iot-1_WorkMode")

    async def test_all_raw_mode_values_map_to_named_options(self) -> None:
        expected = {
            1: "auto",
            2: "sleep",
            3: "skin",
            4: "manual",
            5: "air_drying",
        }
        for raw_value, option in expected.items():
            with self.subTest(raw_value=raw_value):
                self.coordinator.data["iot-1"]["WorkMode"]["value"] = raw_value
                self.assertEqual(self.entity.current_option, option)

        self.coordinator.data["iot-1"]["WorkMode"]["value"] = " 2 "
        self.assertEqual(self.entity.current_option, "sleep")
        self.coordinator.data["iot-1"]["WorkMode"]["value"] = 99
        self.assertIsNone(self.entity.current_option)

    async def test_selecting_mode_writes_workmode_and_marks_power_on(self) -> None:
        await self.entity.async_select_option("sleep")

        self.coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"WorkMode": 2}
        )
        self.assertEqual(self.entity.current_option, "sleep")
        self.assertEqual(self.coordinator.data["iot-1"]["PowerSwitch"]["value"], 1)
        self.assertEqual(self.coordinator.data["iot-1"]["WindSpeed"]["value"], 2)
        self.coordinator.async_set_updated_data.assert_called_once_with(
            self.coordinator.data
        )

    async def test_each_named_mode_writes_its_exact_raw_value(self) -> None:
        expected = {
            "auto": 1,
            "sleep": 2,
            "skin": 3,
            "manual": 4,
            "air_drying": 5,
        }

        for option, raw_value in expected.items():
            with self.subTest(option=option):
                self.coordinator.api.set_device_properties.reset_mock()
                self.coordinator.async_set_updated_data.reset_mock()

                await self.entity.async_select_option(option)

                self.coordinator.api.set_device_properties.assert_awaited_once_with(
                    "iot-1", {"WorkMode": raw_value}
                )
                self.assertEqual(self.entity.current_option, option)
                self.coordinator.async_set_updated_data.assert_called_once_with(
                    self.coordinator.data
                )

    async def test_selecting_mode_while_on_does_not_write_power(self) -> None:
        self.coordinator.data["iot-1"]["PowerSwitch"]["value"] = 1

        await self.entity.async_select_option("auto")

        self.coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"WorkMode": 1}
        )

    async def test_invalid_mode_does_not_write(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported work mode"):
            await self.entity.async_select_option("turbo")

        self.coordinator.api.set_device_properties.assert_not_awaited()
        self.coordinator.async_set_updated_data.assert_not_called()
        self.assertEqual(self.entity.current_option, "manual")

    async def test_cloud_failure_does_not_change_mode(self) -> None:
        self.coordinator.api.set_device_properties.side_effect = RuntimeError(
            "cloud error"
        )

        with self.assertRaisesRegex(HomeAssistantError, "Failed to update") as raised:
            await self.entity.async_select_option("auto")

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual(self.entity.current_option, "manual")
        self.coordinator.async_set_updated_data.assert_not_called()


class Z120ManualGearSelectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.module = load_platform_module("select")

    async def _make_entity(self, properties: dict):
        coordinator = FakeCoordinator(properties)
        entities = await setup_entities(self.module, coordinator)
        return entity_by_unique_id(entities, "iot-1_WindSpeed"), coordinator

    async def test_gear_is_only_current_while_device_is_in_manual_mode(self) -> None:
        entity, coordinator = await self._make_entity(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 4},
                "WindSpeed": {"value": 6},
            }
        )
        self.assertEqual(entity.current_option, "gear_6")

        coordinator.data["iot-1"]["WorkMode"]["value"] = 1
        self.assertIsNone(entity.current_option)
        coordinator.data["iot-1"]["WorkMode"]["value"] = 4
        coordinator.data["iot-1"]["WindSpeed"]["value"] = 7
        self.assertIsNone(entity.current_option)

    async def test_selecting_gear_writes_controls_and_marks_power_on(self) -> None:
        entity, coordinator = await self._make_entity(
            {
                "PowerSwitch": {"value": 0},
                "WorkMode": {"value": 1},
                "WindSpeed": {"value": 1},
            }
        )

        await entity.async_select_option("gear_5")

        coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"WindSpeed": 5, "WorkMode": 4}
        )
        self.assertEqual(coordinator.data["iot-1"]["PowerSwitch"]["value"], 1)
        self.assertEqual(coordinator.data["iot-1"]["WorkMode"]["value"], 4)
        self.assertEqual(coordinator.data["iot-1"]["WindSpeed"]["value"], 5)
        self.assertEqual(entity.current_option, "gear_5")
        coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)

    async def test_lowercase_windspeed_is_used_for_cloud_and_local_updates(self) -> None:
        entity, coordinator = await self._make_entity(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 4},
                "windspeed": {"value": 1},
            }
        )

        await entity.async_select_option("gear_4")

        coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"windspeed": 4, "WorkMode": 4}
        )
        self.assertEqual(coordinator.data["iot-1"]["windspeed"]["value"], 4)
        self.assertNotIn("WindSpeed", coordinator.data["iot-1"])

    async def test_invalid_gear_does_not_write(self) -> None:
        entity, coordinator = await self._make_entity(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 4},
                "WindSpeed": {"value": 1},
            }
        )

        with self.assertRaisesRegex(ValueError, "Unsupported manual gear"):
            await entity.async_select_option("gear_7")

        coordinator.api.set_device_properties.assert_not_awaited()
        coordinator.async_set_updated_data.assert_not_called()
        self.assertEqual(entity.current_option, "gear_1")

    async def test_cloud_failure_does_not_change_gear_or_mode(self) -> None:
        entity, coordinator = await self._make_entity(
            {
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 1},
                "WindSpeed": {"value": 1},
            }
        )
        coordinator.api.set_device_properties.side_effect = RuntimeError("cloud error")

        with self.assertRaisesRegex(HomeAssistantError, "Failed to update") as raised:
            await entity.async_select_option("gear_3")

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual(coordinator.data["iot-1"]["WorkMode"]["value"], 1)
        self.assertEqual(coordinator.data["iot-1"]["WindSpeed"]["value"], 1)
        self.assertIsNone(entity.current_option)
        coordinator.async_set_updated_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
