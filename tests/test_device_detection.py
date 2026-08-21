from __future__ import annotations

from pathlib import Path
import runpy
import unittest


CONST = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "custom_components" / "air352" / "const.py")
)


class Z120DeviceDetectionTests(unittest.TestCase):
    def test_known_product_key_is_preserved(self) -> None:
        device = {"productKey": CONST["Z120_PRODUCT_KEY"]}

        self.assertEqual(
            CONST["resolve_product_key"](device),
            CONST["Z120_PRODUCT_KEY"],
        )

    def test_product_name_recovers_missing_product_key(self) -> None:
        device = {
            "productKey": None,
            "productName": "352@Z120@空气消毒机",
        }

        self.assertEqual(
            CONST["resolve_product_key"](device),
            CONST["Z120_PRODUCT_KEY"],
        )

    def test_product_model_from_device_info_is_supported(self) -> None:
        device = {"productKey": None, "productName": "352 purifier"}
        info = {"productModel": "Z120"}

        self.assertEqual(
            CONST["resolve_product_key"](device, info),
            CONST["Z120_PRODUCT_KEY"],
        )

    def test_known_info_key_overrides_unrecognized_device_key(self) -> None:
        device = {"productKey": "regional-product", "productName": "352 purifier"}
        info = {"productKey": CONST["Z120_PRODUCT_KEY"]}

        self.assertEqual(
            CONST["resolve_product_key"](device, info),
            CONST["Z120_PRODUCT_KEY"],
        )

    def test_product_name_overrides_unrecognized_product_key(self) -> None:
        device = {
            "productKey": "regional-z120-product",
            "productName": "352@Z120@空气消毒机",
        }

        self.assertEqual(
            CONST["resolve_product_key"](device),
            CONST["Z120_PRODUCT_KEY"],
        )

    def test_similar_product_name_does_not_match(self) -> None:
        device = {"productKey": None, "productName": "352 Z1200 purifier"}

        self.assertIsNone(CONST["resolve_product_key"](device))

    def test_z120_name_does_not_override_another_device_category(self) -> None:
        device = {
            "productKey": "water-product",
            "productName": "352 Z120",
            "categoryKey": "WaterPurifier",
        }

        self.assertEqual(
            CONST["resolve_product_key"](device),
            "water-product",
        )

    def test_non_z120_product_key_is_preserved(self) -> None:
        device = {"productKey": "legacy-product", "productName": "352 purifier"}

        self.assertEqual(
            CONST["resolve_product_key"](device),
            "legacy-product",
        )


class InvalidSensorValueTests(unittest.TestCase):
    def test_observed_z120_sentinels_are_invalid(self) -> None:
        observed = {
            "PM25": (65535, "65535"),
            "PM10": (65535, "65535"),
            "AAL": (255, "255"),
            "CurrentTemperature": (327.6, 327.67, "327.6", "327.67"),
            "RelativeHumidity": (327.6, 327.67, "327.6", "327.67"),
        }

        for property_key, values in observed.items():
            for value in values:
                with self.subTest(property_key=property_key, value=value):
                    self.assertTrue(
                        CONST["is_invalid_sensor_value"](
                            property_key,
                            value,
                            CONST["Z120_PRODUCT_KEY"],
                        )
                    )

    def test_z120_sentinels_are_not_generalized_to_other_models(self) -> None:
        self.assertFalse(
            CONST["is_invalid_sensor_value"]("AAL", 255, "another-product")
        )

    def test_valid_z120_values_are_not_filtered(self) -> None:
        valid = {
            "PM25": 0,
            "PM10": 1,
            "AAL": 1,
            "CurrentTemperature": 29.6,
            "RelativeHumidity": 67.7,
            "TVOC": 225,
            "HCHO": 10,
        }

        for property_key, value in valid.items():
            with self.subTest(property_key=property_key):
                self.assertFalse(
                    CONST["is_invalid_sensor_value"](
                        property_key,
                        value,
                        CONST["Z120_PRODUCT_KEY"],
                    )
                )


if __name__ == "__main__":
    unittest.main()
