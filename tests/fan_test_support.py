from __future__ import annotations

import importlib
import sys
import types
from enum import IntFlag
from pathlib import Path
from unittest.mock import AsyncMock


REPO_ROOT = Path(__file__).resolve().parents[1]


class FanEntityFeature(IntFlag):
    SET_SPEED = 1
    OSCILLATE = 2
    DIRECTION = 4
    PRESET_MODE = 8
    TURN_OFF = 16
    TURN_ON = 32


class FanEntity:
    @property
    def supported_features(self):
        return self._attr_supported_features

    @property
    def preset_modes(self):
        return self._attr_preset_modes

    def async_write_ha_state(self) -> None:
        self.write_count = getattr(self, "write_count", 0) + 1


class CoordinatorEntity:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator

    @classmethod
    def __class_getitem__(cls, _item):
        return cls


class EmptyType:
    pass


def _percentage_to_ranged_value(value_range, percentage):
    low, high = value_range
    return percentage * (high - low + 1) / 100


def _ranged_value_to_percentage(value_range, value):
    low, high = value_range
    return int((value - low + 1) * 100 / (high - low + 1))


def load_fan_module():
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith("custom_components.air352"):
            sys.modules.pop(name)
        if name == "homeassistant" or name.startswith("homeassistant."):
            sys.modules.pop(name)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    air352 = types.ModuleType("custom_components.air352")
    air352.__path__ = [str(REPO_ROOT / "custom_components" / "air352")]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.air352"] = air352

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    fan = types.ModuleType("homeassistant.components.fan")
    fan.FanEntity = FanEntity
    fan.FanEntityFeature = FanEntityFeature
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = EmptyType
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = EmptyType
    helpers = types.ModuleType("homeassistant.helpers")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = EmptyType
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    util = types.ModuleType("homeassistant.util")
    percentage = types.ModuleType("homeassistant.util.percentage")
    percentage.percentage_to_ranged_value = _percentage_to_ranged_value
    percentage.ranged_value_to_percentage = _ranged_value_to_percentage

    stub_modules = {
        "homeassistant": homeassistant,
        "homeassistant.components": components,
        "homeassistant.components.fan": fan,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_platform": entity_platform,
        "homeassistant.helpers.update_coordinator": update_coordinator,
        "homeassistant.util": util,
        "homeassistant.util.percentage": percentage,
    }
    sys.modules.update(stub_modules)

    const = types.ModuleType("custom_components.air352.const")
    const.DOMAIN = "air352"
    const.MANUFACTURER = "352"
    const.DEVICE_TYPE_AIR = "AirPurifier"
    const.normalize_device_category = lambda value: value
    sys.modules["custom_components.air352.const"] = const

    coordinator = types.ModuleType("custom_components.air352.coordinator")
    coordinator.Air352Coordinator = EmptyType
    sys.modules["custom_components.air352.coordinator"] = coordinator

    return importlib.import_module("custom_components.air352.fan")


class FakeCoordinator:
    def __init__(self, properties, product_key="a10n269QEvP") -> None:
        self.data = {"iot-1": properties}
        self.device_infos = {
            "iot-1": {
                "productKey": product_key,
                "firmwareVersion": "test-firmware",
            }
        }
        self.api = types.SimpleNamespace(set_device_properties=AsyncMock())


def make_fan(module, properties=None, product_key="a10n269QEvP"):
    if properties is None:
        properties = {
            "PowerSwitch": {"value": 1},
            "WorkMode": {"value": 4},
            "WindSpeed": {"value": 1},
        }
    coordinator = FakeCoordinator(properties, product_key)
    device = {
        "iotId": "iot-1",
        "productKey": product_key,
        "productName": "352 purifier",
    }
    return module.Air352Fan(coordinator, device), coordinator
