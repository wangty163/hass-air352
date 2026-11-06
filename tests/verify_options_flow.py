"""User-Agent options flow regressions against installed Home Assistant Core."""

import inspect
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import frame

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.air352 import async_setup_entry
from custom_components.air352.config_flow import Air352ConfigFlow

LOGIN_PATH = "/api/v1/enduser/login"


@pytest_asyncio.fixture
async def hass(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    if hasattr(frame, "async_setup"):
        frame.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    # Resolve the handler without installing the integration's manifest
    # requirements through HA's loader.
    with patch(
        "homeassistant.config_entries._async_get_flow_handler",
        AsyncMock(return_value=Air352ConfigFlow),
    ):
        yield hass
    await hass.async_stop()


def add_entry(hass, *, data_user_agent=None, options=None):
    data = {"username": "synthetic-account", "password": "synthetic-password"}
    if data_user_agent is not None:
        data["user_agent"] = data_user_agent
    values = {
        "domain": "air352",
        "title": "Synthetic 352",
        "version": 1,
        "minor_version": 1,
        "data": data,
        "options": options or {},
        "source": "user",
        "unique_id": "synthetic-account",
        "discovery_keys": MappingProxyType({}),
        "subentries_data": [],
    }
    parameters = inspect.signature(ConfigEntry).parameters
    entry = ConfigEntry(
        **{key: value for key, value in values.items() if key in parameters}
    )
    hass.config_entries._entries[entry.entry_id] = entry
    return entry


def suggested_user_agent(result):
    (marker,) = result["data_schema"].schema
    assert str(marker) == "user_agent"
    return (marker.description or {}).get("suggested_value")


async def request_headers_after_setup(hass, entry):
    """Run the integration's setup and return headers its 352 client would send."""
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(),
        async_start_push=AsyncMock(),
        async_shutdown=AsyncMock(),
    )
    with (
        patch(
            "custom_components.air352.Air352Coordinator", return_value=coordinator
        ) as coordinator_class,
        patch("custom_components.air352.async_get_clientsession", Mock()),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        # Keep the options update from reloading through HA's real loader.
        patch.object(entry, "add_update_listener", Mock()),
    ):
        await async_setup_entry(hass, entry)
    api = coordinator_class.call_args.args[1]
    return api._352_headers(LOGIN_PATH)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data_user_agent", "options", "expected"),
    [
        (None, None, ""),
        ("Setup/1.0", None, "Setup/1.0"),
        ("Setup/1.0", {"user_agent": "Options/2.0"}, "Options/2.0"),
        ("Setup/1.0", {"user_agent": ""}, ""),
    ],
)
async def test_options_form_opens_with_current_user_agent_suggested(
    hass, data_user_agent, options, expected
):
    entry = add_entry(hass, data_user_agent=data_user_agent, options=options)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert suggested_user_agent(result) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data_user_agent", "options"),
    [
        ("Setup/1.0", None),
        (None, {"user_agent": "Options/2.0"}),
        ("Setup/1.0", {"user_agent": "Options/2.0"}),
    ],
)
async def test_clearing_saved_user_agent_restores_default_headers(
    hass, data_user_agent, options
):
    entry = add_entry(hass, data_user_agent=data_user_agent, options=options)
    assert "User-Agent" in await request_headers_after_setup(hass, entry)

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    # The frontend omits a cleared optional field from the submission.
    result = await hass.config_entries.options.async_configure(flow["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"user_agent": ""}
    assert "User-Agent" not in await request_headers_after_setup(hass, entry)


@pytest.mark.asyncio
async def test_new_user_agent_replaces_setup_value(hass):
    entry = add_entry(hass, data_user_agent="Setup/1.0")

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"user_agent": "  Options/2.0  "}
    )

    headers = await request_headers_after_setup(hass, entry)
    assert headers["User-Agent"] == "Options/2.0"
