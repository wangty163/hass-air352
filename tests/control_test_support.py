from __future__ import annotations

import importlib
import dataclasses
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, Mock


REPO_ROOT = Path(__file__).resolve().parents[1]
Z120_PRODUCT_KEY = "a10n269QEvP"


class CoordinatorEntity:
    def __init__(self, coordinator, context=None) -> None:
        self.coordinator = coordinator
        self.coordinator_context = context

    @classmethod
    def __class_getitem__(cls, _item):
        return cls

    @property
    def available(self):
        return getattr(self.coordinator, "last_update_success", True)


class _WritableEntity:
    def async_write_ha_state(self) -> None:
        self.write_count = getattr(self, "write_count", 0) + 1


class SelectEntity(_WritableEntity):
    @property
    def options(self):
        return self._attr_options


class SwitchEntity(_WritableEntity):
    pass


@dataclass(frozen=True)
class SelectEntityDescription:
    key: str
    name: str | None = None
    icon: str | None = None
    translation_key: str | None = None


@dataclass(frozen=True)
class SwitchEntityDescription:
    key: str
    name: str | None = None
    icon: str | None = None
    translation_key: str | None = None


class EmptyType:
    pass


class HomeAssistantError(Exception):
    pass


def load_platform_module(platform: str):
    """Load one integration platform against a small HA-compatible stub."""
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
    select = types.ModuleType("homeassistant.components.select")
    select.SelectEntity = SelectEntity
    select.SelectEntityDescription = SelectEntityDescription
    switch = types.ModuleType("homeassistant.components.switch")
    switch.SwitchEntity = SwitchEntity
    switch.SwitchEntityDescription = SwitchEntityDescription
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = EmptyType
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = EmptyType
    helpers = types.ModuleType("homeassistant.helpers")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = EmptyType
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = HomeAssistantError

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.select": select,
            "homeassistant.components.switch": switch,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_platform": entity_platform,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.exceptions": exceptions,
        }
    )

    coordinator = types.ModuleType("custom_components.air352.coordinator")
    coordinator.Air352Coordinator = EmptyType
    sys.modules["custom_components.air352.coordinator"] = coordinator

    const = types.ModuleType("custom_components.air352.const")
    const.DOMAIN = "air352"
    const.MANUFACTURER = "352"
    const.DEVICE_TYPE_AIR = "AirPurifier"
    const.DEVICE_TYPE_HUMIDIFIER = "Humidifier"
    const.DEVICE_TYPE_PURIFIER = "WaterPurifier"
    const.Z120_PRODUCT_KEY = Z120_PRODUCT_KEY
    category_aliases = {
        const.DEVICE_TYPE_AIR.lower(): const.DEVICE_TYPE_AIR,
        const.DEVICE_TYPE_HUMIDIFIER.lower(): const.DEVICE_TYPE_HUMIDIFIER,
        const.DEVICE_TYPE_PURIFIER.lower(): const.DEVICE_TYPE_PURIFIER,
    }
    const.normalize_device_category = lambda value: category_aliases.get(
        str(value or "").lower(), value or ""
    )
    sys.modules["custom_components.air352.const"] = const

    if platform == "select":
        fan = types.ModuleType("custom_components.air352.fan")
        fan.PRESET_MODE_AIR_DRYING = "air_drying"
        fan.PRESET_MODE_AUTO = "auto"
        fan.PRESET_MODE_GEAR_PREFIX = "gear_"
        fan.PRESET_MODE_MANUAL = "manual"
        fan.PRESET_MODE_SKIN = "skin"
        fan.PRESET_MODE_SLEEP = "sleep"
        fan.SPEED_RANGE = (1, 6)
        fan.Z120_PRODUCT_KEY = Z120_PRODUCT_KEY
        fan.Z120_WORKMODE_MAP = {
            "auto": 1,
            "sleep": 2,
            "skin": 3,
            "manual": 4,
            "air_drying": 5,
        }

        def gear_level_for_preset(option):
            if not isinstance(option, str) or not option.startswith("gear_"):
                return None
            try:
                level = int(option[5:])
            except ValueError:
                return None
            return level if 1 <= level <= 6 else None

        def normalize_workmode_value(value):
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value.strip())
                except ValueError:
                    return None
            return None

        fan.gear_level_for_preset = gear_level_for_preset
        fan.normalize_workmode_value = normalize_workmode_value
        sys.modules["custom_components.air352.fan"] = fan

    original_dataclass = dataclasses.dataclass

    def compatible_dataclass(*args, **kwargs):
        # The Mac system Python is 3.9, while HA's runtime supports kw_only.
        kwargs.pop("kw_only", None)
        return original_dataclass(*args, **kwargs)

    dataclasses.dataclass = compatible_dataclass
    try:
        return importlib.import_module(f"custom_components.air352.{platform}")
    finally:
        dataclasses.dataclass = original_dataclass


class FakeCoordinator:
    def __init__(
        self,
        properties: dict,
        *,
        product_key: str = Z120_PRODUCT_KEY,
        category_key: str = "AirPurifier",
    ) -> None:
        self.data = {"iot-1": properties}
        self.devices = [
            {
                "iotId": "iot-1",
                "productKey": product_key,
                "productName": "352 purifier",
                "categoryKey": category_key,
            }
        ]
        self.device_infos = {
            "iot-1": {
                "productKey": product_key,
                "firmwareVersion": "test-firmware",
            }
        }
        self.api = types.SimpleNamespace(set_device_properties=AsyncMock())
        self.async_set_updated_data = Mock()
        self.last_update_success = True


class FakeEntry:
    entry_id = "entry-1"


class FakeHass:
    def __init__(self, coordinator: FakeCoordinator) -> None:
        self.data = {"air352": {FakeEntry.entry_id: coordinator}}


async def setup_entities(module, coordinator: FakeCoordinator) -> list:
    entities = []
    await module.async_setup_entry(
        FakeHass(coordinator),
        FakeEntry(),
        lambda new_entities: entities.extend(new_entities),
    )
    return entities


def entity_by_unique_id(entities: list, unique_id: str):
    return next(entity for entity in entities if entity._attr_unique_id == unique_id)
