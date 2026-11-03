from __future__ import annotations

import unittest

from control_test_support import FakeCoordinator, Z120_PRODUCT_KEY, load_platform_module


sensor_module = load_platform_module("sensor")


def make_sensor(
    property_key: str,
    properties: dict,
    *,
    product_key: str | None = Z120_PRODUCT_KEY,
):
    coordinator = FakeCoordinator(properties, product_key=product_key)
    description = next(
        item for item in sensor_module.SENSOR_DESCRIPTIONS if item.key == property_key
    )
    entity = sensor_module.Air352Sensor(
        coordinator,
        coordinator.devices[0],
        description,
    )
    return entity, coordinator


class Z120SensorSentinelTests(unittest.TestCase):
    def test_initial_z120_sentinels_are_unknown(self) -> None:
        observed = {
            "PM25": 65535,
            "PM10": "65535",
            "AAL": 255,
            "CurrentTemperature": 327.67,
            "RelativeHumidity": "327.6",
        }

        for property_key, value in observed.items():
            with self.subTest(property_key=property_key):
                entity, _ = make_sensor(property_key, {property_key: {"value": value}})
                self.assertIsNone(entity.native_value)

    def test_last_valid_measurement_survives_sentinel_and_missing_field(self) -> None:
        entity, coordinator = make_sensor(
            "CurrentTemperature",
            {"CurrentTemperature": {"value": 29.6}},
        )
        self.assertEqual(entity.native_value, 29.6)

        coordinator.data["iot-1"]["CurrentTemperature"] = {"value": 327.6}
        self.assertEqual(entity.native_value, 29.6)

        coordinator.data["iot-1"].pop("CurrentTemperature")
        self.assertEqual(entity.native_value, 29.6)

    def test_invalid_inputs_do_not_publish_a_derived_air_quality_grade(self) -> None:
        properties = {
            "airQualityGrade": {"value": 1},
            "PM25": {"value": 0},
            "PM10": {"value": 1},
            "AAL": {"value": 1},
        }
        entity, coordinator = make_sensor("airQualityGrade", properties)
        self.assertEqual(entity.native_value, "excellent")

        coordinator.data["iot-1"].update(
            {
                "airQualityGrade": {"value": 2},
                "PM25": {"value": 65535},
            }
        )
        self.assertEqual(entity.native_value, "excellent")

        initial_invalid, _ = make_sensor(
            "airQualityGrade",
            {
                "airQualityGrade": {"value": 2},
                "PM25": {"value": 65535},
                "PM10": {"value": 65535},
                "AAL": {"value": 255},
            },
        )
        self.assertIsNone(initial_invalid.native_value)

    def test_new_sentinel_rules_do_not_change_other_models(self) -> None:
        entity, _ = make_sensor(
            "AAL",
            {"AAL": {"value": 255}},
            product_key="another-product",
        )
        self.assertEqual(entity.native_value, 255)

    def test_existing_tvoc_and_hcho_sentinel_filtering_is_preserved(self) -> None:
        for property_key in ("TVOC", "HCHO"):
            with self.subTest(property_key=property_key):
                entity, _ = make_sensor(
                    property_key,
                    {property_key: {"value": 65535}},
                    product_key="another-product",
                )
                self.assertIsNone(entity.native_value)


if __name__ == "__main__":
    unittest.main()
