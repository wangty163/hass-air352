from __future__ import annotations

import unittest

from control_test_support import (
    FakeCoordinator,
    entity_by_unique_id,
    load_platform_module,
    setup_entities,
)


# Air-quality readings that the firmware reports as 0xFFFF while the sensor
# module is not ready yet (for example during power-on warm-up).
MEASUREMENT_KEYS = ("PM25", "PM10", "TVOC", "HCHO", "CO2")

# User-configured set points. 65535 is a legitimate configured value here and
# must never be dropped as a sensor sentinel.
THRESHOLD_KEYS = (
    "PM25ThresholdOn",
    "PM25ThresholdOff",
    "HCHOThresholdOn",
    "HCHOThresholdOff",
    "TVOCThresholdOn",
    "TVOCThresholdOff",
)

SENTINELS = (65535, "65535")


class SensorSentinelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.module = load_platform_module("sensor")
        self.coordinator = FakeCoordinator(
            {key: {"value": 10} for key in MEASUREMENT_KEYS + THRESHOLD_KEYS}
        )
        self.entities = await setup_entities(self.module, self.coordinator)

    def _entity(self, key: str):
        return entity_by_unique_id(self.entities, f"iot-1_{key}")

    def _report(self, key: str, value) -> None:
        self.coordinator.data["iot-1"][key] = {"value": value}

    def test_measurements_report_unknown_for_sentinel(self) -> None:
        for key in MEASUREMENT_KEYS:
            for sentinel in SENTINELS:
                with self.subTest(key=key, sentinel=sentinel):
                    self._report(key, sentinel)
                    self.assertIsNone(self._entity(key).native_value)

    def test_measurements_keep_normal_values(self) -> None:
        for key in MEASUREMENT_KEYS:
            for value in (0, 10, 65534, "10"):
                with self.subTest(key=key, value=value):
                    self._report(key, value)
                    self.assertEqual(self._entity(key).native_value, value)

    def test_sentinel_after_normal_value_does_not_keep_stale_reading(self) -> None:
        for key in MEASUREMENT_KEYS:
            for sentinel in SENTINELS:
                with self.subTest(key=key, sentinel=sentinel):
                    entity = self._entity(key)
                    self._report(key, 12)
                    self.assertEqual(entity.native_value, 12)
                    self._report(key, sentinel)
                    self.assertIsNone(entity.native_value)
                    self._report(key, 13)
                    self.assertEqual(entity.native_value, 13)

    def test_thresholds_are_not_filtered(self) -> None:
        for key in THRESHOLD_KEYS:
            for value in SENTINELS + (0, 10):
                with self.subTest(key=key, value=value):
                    self._report(key, value)
                    self.assertEqual(self._entity(key).native_value, value)

    def test_every_covered_key_is_exposed(self) -> None:
        exposed = {entity._attr_unique_id for entity in self.entities}
        for key in MEASUREMENT_KEYS + THRESHOLD_KEYS:
            with self.subTest(key=key):
                self.assertIn(f"iot-1_{key}", exposed)


if __name__ == "__main__":
    unittest.main()
