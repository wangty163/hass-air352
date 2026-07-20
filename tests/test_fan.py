from __future__ import annotations

import unittest

from fan_test_support import (
    FanEntityFeature,
    HomeAssistantError,
    FakeCoordinator,
    load_fan_module,
    make_fan,
    setup_fans,
)


fan_module = load_fan_module()


class FanContractTests(unittest.TestCase):
    def test_helper_rejects_invalid_cloud_and_gear_values(self):
        self.assertEqual(fan_module.normalize_workmode_value(True), 1)
        self.assertEqual(fan_module.normalize_workmode_value(" 4 "), 4)
        self.assertIsNone(fan_module.normalize_workmode_value("bad"))
        self.assertIsNone(fan_module.normalize_workmode_value(None))
        self.assertIsNone(fan_module.gear_level_for_preset("auto"))
        self.assertIsNone(fan_module.gear_level_for_preset("gear_bad"))
        self.assertIsNone(fan_module.gear_level_for_preset("gear_0"))
        self.assertIsNone(fan_module.gear_level_for_preset("gear_7"))
        self.assertIsNone(
            fan_module.preset_for_workmode_value(
                fan_module.Z120_PRODUCT_KEY, 99, 1
            )
        )

    def test_z120_advertises_named_gears_instead_of_percentage_speed(self):
        entity, _ = make_fan(fan_module)

        self.assertFalse(entity._attr_supported_features & FanEntityFeature.SET_SPEED)
        self.assertTrue(entity._attr_supported_features & FanEntityFeature.PRESET_MODE)
        self.assertTrue(entity._attr_supported_features & FanEntityFeature.TURN_ON)
        self.assertTrue(entity._attr_supported_features & FanEntityFeature.TURN_OFF)
        self.assertEqual(
            entity.preset_modes,
            [
                "auto",
                "sleep",
                "skin",
                "air_drying",
                "gear_1",
                "gear_2",
                "gear_3",
                "gear_4",
                "gear_5",
                "gear_6",
            ],
        )
        self.assertNotIn("manual", entity.preset_modes)

    def test_non_z120_keeps_legacy_percentage_contract(self):
        entity, _ = make_fan(fan_module, product_key="legacy-product")

        self.assertTrue(entity._attr_supported_features & FanEntityFeature.SET_SPEED)
        self.assertEqual(entity.preset_modes, ["auto", "sleep", "manual"])

    def test_unique_id_is_unchanged(self):
        entity, _ = make_fan(fan_module)

        self.assertEqual(entity._attr_unique_id, "iot-1_fan")

    def test_z120_compatibility_fan_is_disabled_by_default(self):
        entity, _ = make_fan(fan_module)
        legacy_entity, _ = make_fan(fan_module, product_key="legacy-product")

        self.assertFalse(entity._attr_entity_registry_enabled_default)
        self.assertTrue(
            getattr(legacy_entity, "_attr_entity_registry_enabled_default", True)
        )

    def test_power_percentage_and_availability_state(self):
        entity, coordinator = make_fan(fan_module)
        self.assertTrue(entity.is_on)
        self.assertEqual(entity.percentage, 16)
        self.assertTrue(entity.available)

        coordinator.data["iot-1"]["PowerSwitch"]["value"] = 0
        coordinator.data["iot-1"]["WindSpeed"]["value"] = 0
        self.assertFalse(entity.is_on)
        self.assertEqual(entity.percentage, 0)

        coordinator.data["iot-1"].pop("PowerSwitch")
        coordinator.data["iot-1"].pop("WindSpeed")
        self.assertIsNone(entity.is_on)
        self.assertIsNone(entity.percentage)

        coordinator.data.clear()
        self.assertFalse(entity.available)

    def test_z120_manual_workmode_reports_specific_gear(self):
        for level in range(1, 7):
            with self.subTest(level=level):
                entity, _ = make_fan(
                    fan_module,
                    properties={
                        "PowerSwitch": {"value": 1},
                        "WorkMode": {"value": 4},
                        "WindSpeed": {"value": level},
                    },
                )
                self.assertEqual(entity.preset_mode, f"gear_{level}")

    def test_z120_manual_workmode_rejects_unknown_gear(self):
        for speed in (None, 0, 7, "bad"):
            with self.subTest(speed=speed):
                properties = {
                    "PowerSwitch": {"value": 1},
                    "WorkMode": {"value": 4},
                }
                if speed is not None:
                    properties["WindSpeed"] = {"value": speed}
                entity, _ = make_fan(fan_module, properties=properties)
                self.assertIsNone(entity.preset_mode)

    def test_z120_non_manual_workmodes_ignore_stale_speed(self):
        expected = {1: "auto", 2: "sleep", 3: "skin", 5: "air_drying"}
        for workmode, preset in expected.items():
            with self.subTest(workmode=workmode):
                entity, _ = make_fan(
                    fan_module,
                    properties={
                        "PowerSwitch": {"value": 1},
                        "WorkMode": {"value": workmode},
                        "WindSpeed": {"value": 6},
                    },
                )
                self.assertEqual(entity.preset_mode, preset)


class FanActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_off_updates_cloud_and_local_state(self):
        entity, coordinator = make_fan(fan_module)

        await entity.async_turn_off()

        coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"PowerSwitch": 0}
        )
        self.assertEqual(
            coordinator.data["iot-1"]["PowerSwitch"]["value"], 0
        )
        coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)

    async def test_direct_percentage_method_preserves_legacy_mapping(self):
        entity, coordinator = make_fan(fan_module)

        await entity.async_set_percentage(83)

        coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"WindSpeed": 5, "WorkMode": 4}
        )
        self.assertEqual(entity.preset_mode, "gear_5")

    async def test_zero_percentage_turns_off(self):
        entity, coordinator = make_fan(fan_module)

        await entity.async_set_percentage(0)

        coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1", {"PowerSwitch": 0}
        )
        self.assertFalse(entity.is_on)

    async def test_named_gears_write_manual_mode_and_speed(self):
        for speed_key in ("WindSpeed", "windspeed", None):
            for level in range(1, 7):
                with self.subTest(speed_key=speed_key, level=level):
                    properties = {
                        "PowerSwitch": {"value": 1},
                        "WorkMode": {"value": 1},
                    }
                    if speed_key is not None:
                        properties[speed_key] = {"value": 1}
                    entity, coordinator = make_fan(
                        fan_module, properties=properties
                    )

                    await entity.async_set_preset_mode(f"gear_{level}")

                    expected_key = speed_key or "WindSpeed"
                    coordinator.api.set_device_properties.assert_awaited_once_with(
                        "iot-1",
                        {expected_key: level, "WorkMode": 4},
                    )
                    self.assertEqual(
                        coordinator.data["iot-1"][expected_key]["value"], level
                    )
                    self.assertEqual(
                        coordinator.data["iot-1"]["WorkMode"]["value"], 4
                    )
                    self.assertEqual(entity.preset_mode, f"gear_{level}")
                    coordinator.async_set_updated_data.assert_called_once_with(
                        coordinator.data
                    )

    async def test_turn_on_with_named_gear_also_powers_on(self):
        entity, coordinator = make_fan(fan_module)

        await entity.async_turn_on(preset_mode="gear_4")

        coordinator.api.set_device_properties.assert_awaited_once_with(
            "iot-1",
            {"PowerSwitch": 1, "WindSpeed": 4, "WorkMode": 4},
        )

    async def test_existing_percentage_turn_on_mapping_is_preserved(self):
        expected = {16: 1, 33: 2, 50: 3, 66: 4, 83: 5, 100: 6}
        for percentage, level in expected.items():
            with self.subTest(percentage=percentage):
                entity, coordinator = make_fan(fan_module)

                await entity.async_turn_on(percentage=percentage)

                coordinator.api.set_device_properties.assert_awaited_once_with(
                    "iot-1",
                    {"PowerSwitch": 1, "WindSpeed": level, "WorkMode": 4},
                )

    async def test_existing_non_manual_modes_remain_writable(self):
        expected = {
            "auto": 1,
            "sleep": 2,
            "skin": 3,
            "air_drying": 5,
        }
        for preset, workmode in expected.items():
            with self.subTest(preset=preset):
                entity, coordinator = make_fan(fan_module)

                await entity.async_set_preset_mode(preset)

                coordinator.api.set_device_properties.assert_awaited_once_with(
                    "iot-1", {"WorkMode": workmode}
                )

    async def test_invalid_preset_does_not_write(self):
        entity, coordinator = make_fan(fan_module)

        await entity.async_set_preset_mode("gear_7")

        coordinator.api.set_device_properties.assert_not_awaited()

    async def test_api_failure_does_not_update_local_state(self):
        entity, coordinator = make_fan(
            fan_module,
            properties={
                "PowerSwitch": {"value": 1},
                "WorkMode": {"value": 1},
                "WindSpeed": {"value": 1},
            },
        )
        coordinator.api.set_device_properties.side_effect = RuntimeError("cloud error")

        with self.assertRaisesRegex(HomeAssistantError, "Failed to update") as raised:
            await entity.async_set_preset_mode("gear_5")

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual(coordinator.data["iot-1"]["WorkMode"]["value"], 1)
        self.assertEqual(coordinator.data["iot-1"]["WindSpeed"]["value"], 1)
        coordinator.async_set_updated_data.assert_not_called()


class FanSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_z120_fan_registers_after_empty_first_snapshot(self):
        coordinator = FakeCoordinator({})

        entities = await setup_fans(fan_module, coordinator)

        self.assertEqual(len(entities), 1)
        entity = entities[0]
        self.assertEqual(entity._attr_unique_id, "iot-1_fan")
        self.assertFalse(entity.available)

        coordinator.data["iot-1"]["PowerSwitch"] = {"value": 1}
        self.assertTrue(entity.available)
        self.assertTrue(entity.is_on)


if __name__ == "__main__":
    unittest.main()
