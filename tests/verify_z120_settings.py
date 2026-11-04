"""Z120 composite settings writes through the real coordinator and switch."""

import inspect
import sys
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
import pytest_asyncio
from homeassistant.config_entries import ConfigEntries, ConfigEntry, current_entry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import frame

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.air352.api import Air352ApiClient
from custom_components.air352.const import Z120_PRODUCT_KEY
from custom_components.air352.coordinator import Air352Coordinator
from custom_components.air352.switch import SWITCH_DESCRIPTIONS, Air352Switch

IOT_ID = "synthetic-z120"
SETTINGS_REPORT = call(IOT_ID, {"SetResearchAll": 1})
SETTINGS = {
    "StandbySensorSwitch": 1,
    "SmartModeSwitch": 0,
    "MicrowaveSensor": 0,
    "PM25ThresholdOn": 35,
    "PM25ThresholdOff": 5,
    "HCHOThresholdOn": 80,
    "HCHOThresholdOff": 30,
    "TVOCThresholdOn": 600,
    "TVOCThresholdOff": 300,
}


def reported(values, time_ms):
    return {key: {"value": value, "time": time_ms} for key, value in values.items()}


@pytest_asyncio.fixture
async def runtime(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    if hasattr(frame, "async_setup"):
        frame.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    values = {
        "domain": "air352",
        "title": "Synthetic 352",
        "version": 1,
        "minor_version": 1,
        "data": {"username": "synthetic-account", "password": "synthetic-password"},
        "options": {},
        "source": "user",
        "unique_id": "synthetic-account",
        "discovery_keys": MappingProxyType({}),
        "subentries_data": [],
    }
    parameters = inspect.signature(ConfigEntry).parameters
    entry = ConfigEntry(
        **{key: value for key, value in values.items() if key in parameters}
    )
    api = Air352ApiClient(Mock(), "synthetic-account", "synthetic-password")
    api.set_device_properties = AsyncMock()
    api.get_device_properties = AsyncMock()
    entry_context = current_entry.set(entry)
    try:
        coordinator = Air352Coordinator(hass, api, "synthetic-account")
    finally:
        current_entry.reset(entry_context)
    with patch("custom_components.air352.coordinator.asyncio.sleep", AsyncMock()):
        yield api, coordinator
    await coordinator.async_shutdown()
    await hass.async_stop()


def add_device(coordinator, cached, *, product_key=Z120_PRODUCT_KEY):
    device = {
        "iotId": IOT_ID,
        "productKey": product_key,
        "productName": "Synthetic 352",
        "categoryKey": "AirPurifier",
    }
    coordinator.devices = [device]
    coordinator._property_state.merge_device(IOT_ID, cached, source="rest")
    coordinator.async_set_updated_data(coordinator._property_state.snapshot())
    return device


def switch(coordinator, device, key):
    description = next(item for item in SWITCH_DESCRIPTIONS if item.key == key)
    return Air352Switch(coordinator, device, description)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [{}, reported({"MicrowaveSensor": 0}, 9_000)],
    ids=["empty", "partial"],
)
async def test_incomplete_settings_read_blocks_write_despite_complete_cache(
    runtime, response
):
    api, coordinator = runtime
    device = add_device(coordinator, reported(SETTINGS, 1_000))
    api.get_device_properties.return_value = response
    microwave = switch(coordinator, device, "MicrowaveSensor")

    with pytest.raises(HomeAssistantError, match="did not report valid settings"):
        await microwave.async_turn_on()

    assert api.set_device_properties.await_args_list == [SETTINGS_REPORT]
    assert microwave.is_on is False


@pytest.mark.asyncio
async def test_complete_settings_read_replaces_stale_cache(runtime):
    api, coordinator = runtime
    stale = dict(SETTINGS, SmartModeSwitch=1, PM25ThresholdOn=10)
    device = add_device(coordinator, reported(stale, 1_000))
    api.get_device_properties.return_value = reported(SETTINGS, 9_000)

    await switch(coordinator, device, "MicrowaveSensor").async_turn_on()

    assert api.set_device_properties.await_args_list == [
        SETTINGS_REPORT,
        call(IOT_ID, dict(SETTINGS, MicrowaveSensor=1)),
        SETTINGS_REPORT,
    ]


@pytest.mark.asyncio
async def test_unconfirmed_command_is_kept_by_next_composite_write(runtime):
    api, coordinator = runtime
    device = add_device(coordinator, reported(SETTINGS, 1_000))
    # The device has not yet reported the first command when the second is sent.
    api.get_device_properties.return_value = reported(SETTINGS, 9_000)

    await switch(coordinator, device, "MicrowaveSensor").async_turn_on()
    await switch(coordinator, device, "SmartModeSwitch").async_turn_on()

    assert api.set_device_properties.await_args_list[-2] == call(
        IOT_ID,
        dict(SETTINGS, MicrowaveSensor=1, SmartModeSwitch=1, StandbySensorSwitch=1),
    )


@pytest.mark.asyncio
async def test_non_z120_settings_switch_sends_no_z120_commands(runtime):
    api, coordinator = runtime
    device = add_device(
        coordinator, reported(SETTINGS, 1_000), product_key="legacy-product"
    )

    await switch(coordinator, device, "SmartModeSwitch").async_turn_on()

    assert api.set_device_properties.await_args_list == [
        call(IOT_ID, {"SmartModeSwitch": 1})
    ]
    api.get_device_properties.assert_not_awaited()
