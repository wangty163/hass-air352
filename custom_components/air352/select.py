from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_TYPE_AIR,
    DOMAIN,
    MANUFACTURER,
    Z120_PRODUCT_KEY,
    normalize_device_category,
)
from .coordinator import Air352Coordinator
from .entity import async_set_device_properties
from .fan import (
    PRESET_MODE_AIR_DRYING,
    PRESET_MODE_AUTO,
    PRESET_MODE_GEAR_PREFIX,
    PRESET_MODE_MANUAL,
    PRESET_MODE_SKIN,
    PRESET_MODE_SLEEP,
    SPEED_RANGE,
    Z120_WORKMODE_MAP,
    gear_level_for_preset,
    normalize_workmode_value,
)

MODE_OPTIONS = [
    PRESET_MODE_MANUAL,
    PRESET_MODE_AUTO,
    PRESET_MODE_SLEEP,
    PRESET_MODE_SKIN,
    PRESET_MODE_AIR_DRYING,
]
MODE_BY_VALUE = {value: option for option, value in Z120_WORKMODE_MAP.items()}
GEAR_OPTIONS = [
    f"{PRESET_MODE_GEAR_PREFIX}{level}"
    for level in range(SPEED_RANGE[0], SPEED_RANGE[1] + 1)
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: Air352Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[Air352Select] = []

    for device in coordinator.devices:
        if normalize_device_category(device.get("categoryKey")) != DEVICE_TYPE_AIR:
            continue

        iot_id = device["iotId"]
        info = coordinator.device_infos.get(iot_id, {})
        product_key = device.get("productKey") or info.get("productKey")
        if product_key != Z120_PRODUCT_KEY:
            continue

        # Register the known Z120 controls even if the first property poll failed.
        # Availability and state recover automatically on the next coordinator poll.
        entities.extend(
            (
                Air352WorkModeSelect(coordinator, device),
                Air352ManualGearSelect(coordinator, device),
            )
        )

    async_add_entities(entities)


class Air352Select(CoordinatorEntity[Air352Coordinator], SelectEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Air352Coordinator,
        device: dict[str, Any],
        *,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = device["iotId"]
        self._attr_unique_id = f"{self._iot_id}_{unique_id_suffix}"
        info = coordinator.device_infos.get(self._iot_id, {})
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._iot_id)},
            "name": device.get("productName", "352 Device"),
            "manufacturer": MANUFACTURER,
            "model": info.get("firmwareVersion", device.get("productModel", "")),
        }

    def _properties(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(self._iot_id, {})

    def _property_value(self, key: str) -> Any:
        prop = self._properties().get(key)
        if prop is None:
            return None
        return prop.get("value") if isinstance(prop, dict) else prop

    def _speed_key(self) -> str | None:
        props = self._properties()
        if "WindSpeed" in props:
            return "WindSpeed"
        if "windspeed" in props:
            return "windspeed"
        return None

    def _update_local_state(self, values: dict[str, int]) -> None:
        props = self._properties()
        for key, value in values.items():
            prop = props.get(key)
            if isinstance(prop, dict):
                prop["value"] = value
            else:
                props[key] = {"value": value}
        self.coordinator.async_set_updated_data(self.coordinator.data)

class Air352WorkModeSelect(Air352Select):
    _attr_translation_key = "work_mode"
    _attr_icon = "mdi:air-purifier"
    _attr_options = MODE_OPTIONS

    def __init__(self, coordinator: Air352Coordinator, device: dict[str, Any]) -> None:
        super().__init__(
            coordinator,
            device,
            unique_id_suffix="WorkMode",
        )

    @property
    def current_option(self) -> str | None:
        value = normalize_workmode_value(self._property_value("WorkMode"))
        return MODE_BY_VALUE.get(value)

    async def async_select_option(self, option: str) -> None:
        if option not in Z120_WORKMODE_MAP:
            raise ValueError(f"Unsupported work mode: {option}")
        values = {"WorkMode": Z120_WORKMODE_MAP[option]}
        await async_set_device_properties(self.coordinator, self._iot_id, values)
        self._update_local_state({**values, "PowerSwitch": 1})

    @property
    def available(self) -> bool:
        return super().available and "WorkMode" in self._properties()


class Air352ManualGearSelect(Air352Select):
    _attr_translation_key = "manual_gear"
    _attr_icon = "mdi:fan-speed-2"
    _attr_options = GEAR_OPTIONS

    def __init__(self, coordinator: Air352Coordinator, device: dict[str, Any]) -> None:
        super().__init__(
            coordinator,
            device,
            unique_id_suffix="WindSpeed",
        )

    @property
    def current_option(self) -> str | None:
        work_mode = normalize_workmode_value(self._property_value("WorkMode"))
        if work_mode != Z120_WORKMODE_MAP[PRESET_MODE_MANUAL]:
            return None
        speed_key = self._speed_key()
        if speed_key is None:
            return None
        speed = normalize_workmode_value(self._property_value(speed_key))
        if speed is None or not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
            return None
        return f"{PRESET_MODE_GEAR_PREFIX}{speed}"

    async def async_select_option(self, option: str) -> None:
        level = gear_level_for_preset(option)
        if level is None:
            raise ValueError(f"Unsupported manual gear: {option}")
        speed_key = self._speed_key() or "WindSpeed"
        values = {
            speed_key: level,
            "WorkMode": Z120_WORKMODE_MAP[PRESET_MODE_MANUAL],
        }
        await async_set_device_properties(self.coordinator, self._iot_id, values)
        self._update_local_state({**values, "PowerSwitch": 1})

    @property
    def available(self) -> bool:
        return super().available and self._speed_key() is not None
