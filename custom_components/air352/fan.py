from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import DOMAIN, MANUFACTURER, DEVICE_TYPE_AIR, normalize_device_category
from .coordinator import Air352Coordinator

SPEED_RANGE = (1, 6)

PRESET_MODE_AUTO = "auto"
PRESET_MODE_SLEEP = "sleep"
PRESET_MODE_MANUAL = "manual"
PRESET_MODE_SKIN = "skin"
PRESET_MODE_AIR_DRYING = "air_drying"
PRESET_MODE_GEAR_PREFIX = "gear_"

Z120_PRODUCT_KEY = "a10n269QEvP"
Z120_GEAR_PRESET_MODES = [
    f"{PRESET_MODE_GEAR_PREFIX}{level}"
    for level in range(SPEED_RANGE[0], SPEED_RANGE[1] + 1)
]

FALLBACK_WORKMODE_MAP = {
    PRESET_MODE_AUTO: 1,
    PRESET_MODE_SLEEP: 3,
    PRESET_MODE_MANUAL: 2,
}

Z120_WORKMODE_MAP = {
    PRESET_MODE_AUTO: 1,
    PRESET_MODE_SLEEP: 2,
    PRESET_MODE_SKIN: 3,
    PRESET_MODE_MANUAL: 4,
    PRESET_MODE_AIR_DRYING: 5,
}

WORKMODE_PROFILES: dict[str, Mapping[str, int]] = {
    Z120_PRODUCT_KEY: Z120_WORKMODE_MAP,
}

# Backwards-compatible aliases for callers that imported the old constants.
PRESET_MODES = list(FALLBACK_WORKMODE_MAP)
WORKMODE_MAP = FALLBACK_WORKMODE_MAP
WORKMODE_REVERSE = {value: preset for preset, value in WORKMODE_MAP.items()}


def get_workmode_map(product_key: str | None) -> Mapping[str, int]:
    """Return the device-specific WorkMode map, or the legacy fallback."""
    return WORKMODE_PROFILES.get(product_key or "", FALLBACK_WORKMODE_MAP)


def get_preset_modes(product_key: str | None) -> list[str]:
    """Return selectable presets for a product (standby is never a preset)."""
    if product_key == Z120_PRODUCT_KEY:
        return [
            PRESET_MODE_AUTO,
            PRESET_MODE_SLEEP,
            PRESET_MODE_SKIN,
            PRESET_MODE_AIR_DRYING,
            *Z120_GEAR_PRESET_MODES,
        ]
    return list(get_workmode_map(product_key))


def get_supported_features(product_key: str | None) -> FanEntityFeature:
    """Return product-specific features exposed to Home Assistant."""
    features = (
        FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    if product_key != Z120_PRODUCT_KEY:
        features |= FanEntityFeature.SET_SPEED
    return features


def workmode_value_for_preset(product_key: str | None, preset_mode: str) -> int | None:
    """Translate an HA preset to the product's WorkMode value."""
    return get_workmode_map(product_key).get(preset_mode)


def normalize_workmode_value(value: Any) -> int | None:
    """Normalize integer and integer-string WorkMode values from the cloud."""
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


def gear_level_for_preset(preset_mode: str) -> int | None:
    """Return the 1-based Z120 gear encoded by a preset name."""
    if not preset_mode.startswith(PRESET_MODE_GEAR_PREFIX):
        return None
    try:
        level = int(preset_mode[len(PRESET_MODE_GEAR_PREFIX) :])
    except ValueError:
        return None
    return level if SPEED_RANGE[0] <= level <= SPEED_RANGE[1] else None


def preset_for_workmode_value(
    product_key: str | None, value: Any, speed_value: Any = None
) -> str | None:
    """Translate a cloud WorkMode value to an HA preset."""
    normalized = normalize_workmode_value(value)
    if normalized is None:
        return None
    if (
        product_key == Z120_PRODUCT_KEY
        and normalized == Z120_WORKMODE_MAP[PRESET_MODE_MANUAL]
    ):
        speed = normalize_workmode_value(speed_value)
        if speed is None or not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
            return None
        return f"{PRESET_MODE_GEAR_PREFIX}{speed}"
    return next(
        (
            preset
            for preset, workmode in get_workmode_map(product_key).items()
            if workmode == normalized
        ),
        None,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Air352Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in coordinator.devices:
        category = normalize_device_category(device.get("categoryKey"))
        if category != DEVICE_TYPE_AIR:
            continue
        iot_id = device["iotId"]
        props = coordinator.data.get(iot_id, {}) if coordinator.data else {}
        if "PowerSwitch" in props:
            entities.append(Air352Fan(coordinator, device))
    async_add_entities(entities)


class Air352Fan(CoordinatorEntity[Air352Coordinator], FanEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "air_purifier"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_preset_modes = PRESET_MODES
    _attr_speed_count = 6

    def __init__(self, coordinator: Air352Coordinator, device: dict) -> None:
        super().__init__(coordinator)
        self._iot_id = device["iotId"]
        self._attr_unique_id = f"{self._iot_id}_fan"
        info = coordinator.device_infos.get(self._iot_id, {})
        self._product_key = device.get("productKey") or info.get("productKey")
        self._attr_supported_features = get_supported_features(self._product_key)
        self._attr_preset_modes = get_preset_modes(self._product_key)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._iot_id)},
            "name": device.get("productName", "352 Device"),
            "manufacturer": MANUFACTURER,
            "model": info.get("firmwareVersion", device.get("productModel", "")),
        }

    def _get_prop_value(self, key: str) -> Any:
        props = self.coordinator.data.get(self._iot_id, {})
        prop = props.get(key)
        if prop is None:
            return None
        return prop.get("value") if isinstance(prop, dict) else prop

    def _get_speed_key(self) -> str | None:
        props = self.coordinator.data.get(self._iot_id, {})
        if "WindSpeed" in props:
            return "WindSpeed"
        if "windspeed" in props:
            return "windspeed"
        return None

    @property
    def is_on(self) -> bool | None:
        val = self._get_prop_value("PowerSwitch")
        if val is None:
            return None
        return bool(val)

    @property
    def percentage(self) -> int | None:
        speed_key = self._get_speed_key()
        if speed_key is None:
            return None
        val = self._get_prop_value(speed_key)
        if val is None or val == 0:
            return 0
        return ranged_value_to_percentage(SPEED_RANGE, val)

    @property
    def preset_mode(self) -> str | None:
        val = self._get_prop_value("WorkMode")
        if val is None:
            return None
        speed_key = self._get_speed_key()
        speed = self._get_prop_value(speed_key) if speed_key is not None else None
        return preset_for_workmode_value(self._product_key, val, speed)

    def _properties_for_preset(self, preset_mode: str) -> dict[str, int]:
        if self._product_key == Z120_PRODUCT_KEY:
            gear_level = gear_level_for_preset(preset_mode)
            if gear_level is not None:
                speed_key = self._get_speed_key() or "WindSpeed"
                return {
                    speed_key: gear_level,
                    "WorkMode": Z120_WORKMODE_MAP[PRESET_MODE_MANUAL],
                }
        workmode = workmode_value_for_preset(self._product_key, preset_mode)
        return {"WorkMode": workmode} if workmode is not None else {}

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        props: dict[str, int] = {"PowerSwitch": 1}
        if preset_mode is not None:
            props.update(self._properties_for_preset(preset_mode))
        if percentage is not None:
            speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
            speed_key = self._get_speed_key() or "WindSpeed"
            props[speed_key] = speed
            props.setdefault(
                "WorkMode",
                get_workmode_map(self._product_key)[PRESET_MODE_MANUAL],
            )
        await self.coordinator.api.set_device_properties(self._iot_id, props)
        self._update_local_state(props)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.api.set_device_properties(self._iot_id, {"PowerSwitch": 0})
        self._update_local_state({"PowerSwitch": 0})

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        speed_key = self._get_speed_key() or "WindSpeed"
        props = {
            speed_key: speed,
            "WorkMode": get_workmode_map(self._product_key)[PRESET_MODE_MANUAL],
        }
        await self.coordinator.api.set_device_properties(self._iot_id, props)
        self._update_local_state(props)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        props = self._properties_for_preset(preset_mode)
        if not props:
            return
        await self.coordinator.api.set_device_properties(self._iot_id, props)
        self._update_local_state(props)

    def _update_local_state(self, values: dict[str, int]) -> None:
        props = self.coordinator.data.get(self._iot_id, {})
        for key, value in values.items():
            prop = props.get(key)
            if isinstance(prop, dict):
                prop["value"] = value
            else:
                props[key] = {"value": value}
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._iot_id in (self.coordinator.data or {})
