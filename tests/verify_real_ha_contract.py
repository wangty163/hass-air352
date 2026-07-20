from __future__ import annotations

import unittest
from types import SimpleNamespace

from homeassistant.components.fan import FanEntityFeature

from custom_components.air352.fan import (
    Air352Fan,
    Z120_PRODUCT_KEY,
    get_preset_modes,
    get_supported_features,
)


class RealHomeAssistantContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entity = object.__new__(Air352Fan)
        self.entity._iot_id = "iot-1"
        self.entity._product_key = Z120_PRODUCT_KEY
        self.entity._attr_supported_features = get_supported_features(
            Z120_PRODUCT_KEY
        )
        self.entity._attr_preset_modes = get_preset_modes(Z120_PRODUCT_KEY)
        self.entity.coordinator = SimpleNamespace(
            data={
                "iot-1": {
                    "PowerSwitch": {"value": 1},
                    "WorkMode": {"value": 4},
                    "WindSpeed": {"value": 1},
                }
            }
        )

    def test_z120_real_fan_state_has_named_gear_without_percentage(self) -> None:
        self.assertFalse(
            self.entity.supported_features & FanEntityFeature.SET_SPEED
        )
        self.assertEqual(
            self.entity.state_attributes,
            {"preset_mode": "gear_1"},
        )
        self.assertNotIn("percentage", self.entity.state_attributes)
        self.assertNotIn("percentage_step", self.entity.state_attributes)

    def test_z120_real_fan_capabilities_publish_ten_named_presets(self) -> None:
        self.assertEqual(
            self.entity.capability_attributes["preset_modes"],
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
        self.assertNotIn("percentage_step", self.entity.capability_attributes)


if __name__ == "__main__":
    unittest.main()
