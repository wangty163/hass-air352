"""Offline recovery regressions against installed Home Assistant Core."""

import asyncio
import gzip
import inspect
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
import pytest_asyncio
from homeassistant.config_entries import (
    ConfigEntries,
    ConfigEntry,
    ConfigEntryState,
    current_entry,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import frame
from homeassistant.helpers.update_coordinator import UpdateFailed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.air352 import async_setup_entry
from custom_components.air352.api import (
    Air352ApiClient,
    Air352ApiError,
    Air352AuthError,
    Air352ConnectionError,
)
from custom_components.air352.coordinator import Air352Coordinator
from custom_components.air352.mobile_channel import Air352MobileChannel


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
    object.__setattr__(entry, "state", ConfigEntryState.SETUP_IN_PROGRESS)
    api = SimpleNamespace(
        authenticate=AsyncMock(),
        get_device_list=AsyncMock(return_value=[{"iotId": "synthetic-device"}]),
        get_device_info=AsyncMock(return_value={}),
        get_device_properties=AsyncMock(return_value={"PM25": {"value": 12}}),
    )
    entry_context = current_entry.set(entry)
    try:
        coordinator = Air352Coordinator(hass, api, "synthetic-account")
    finally:
        current_entry.reset(entry_context)
    yield hass, entry, api, coordinator
    await coordinator.async_shutdown()
    await hass.async_stop()


async def start_coordinator(coordinator):
    await coordinator.async_config_entry_first_refresh()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        Air352ApiError(500, "gateway timeout"),
        Air352ConnectionError("offline"),
        TimeoutError(),
        aiohttp.ClientConnectionError(),
    ],
)
async def test_bootstrap_outage_becomes_native_ha_retry(runtime, failure):
    _, _, api, coordinator = runtime
    api.authenticate.side_effect = failure
    with pytest.raises(ConfigEntryNotReady):
        await start_coordinator(coordinator)
    api.authenticate.side_effect = None
    await start_coordinator(coordinator)
    assert coordinator.last_update_success
    assert coordinator.data["synthetic-device"]["PM25"]["value"] == 12


@pytest.mark.asyncio
async def test_bad_credentials_start_reauth_instead_of_retry(runtime):
    _, _, api, coordinator = runtime
    api.authenticate.side_effect = Air352AuthError("invalid credentials")
    with pytest.raises(ConfigEntryAuthFailed):
        await start_coordinator(coordinator)


@pytest.mark.asyncio
async def test_complete_read_failure_is_not_reported_as_healthy(runtime):
    _, _, api, coordinator = runtime
    await start_coordinator(coordinator)
    api.get_device_properties.side_effect = Air352ConnectionError("offline")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.data["synthetic-device"]["PM25"]["value"] == 12
    api.get_device_properties.side_effect = None
    api.get_device_properties.return_value = {"PM25": {"value": 13}}
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data["synthetic-device"]["PM25"]["value"] == 13


@pytest.mark.asyncio
async def test_first_read_failure_retries_instead_of_creating_empty_entities(runtime):
    _, _, api, coordinator = runtime
    api.get_device_properties.side_effect = Air352ConnectionError("offline")
    with pytest.raises(ConfigEntryNotReady):
        await start_coordinator(coordinator)


@pytest.mark.asyncio
async def test_gather_does_not_swallow_authentication_failure(runtime):
    _, _, api, coordinator = runtime
    api.get_device_properties.side_effect = Air352AuthError("rejected session")
    with pytest.raises(ConfigEntryAuthFailed):
        await start_coordinator(coordinator)


@pytest.mark.asyncio
async def test_one_unavailable_device_does_not_disable_healthy_devices(runtime):
    _, _, api, coordinator = runtime
    coordinator.devices = [{"iotId": "good"}, {"iotId": "offline"}]
    api.get_device_properties.side_effect = [
        {"PM25": {"value": 14}},
        Air352ConnectionError("offline"),
    ]
    data = await coordinator._async_update_data()
    assert data["good"]["PM25"]["value"] == 14


@pytest.mark.asyncio
async def test_shutdown_cancels_native_coordinator_and_push(runtime):
    _, _, _, coordinator = runtime
    channel = SimpleNamespace(async_stop=AsyncMock())
    coordinator._mobile_channel = channel
    await coordinator.async_shutdown()
    assert coordinator._shutdown_requested
    assert coordinator._mobile_channel is None
    channel.async_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_push_binding_forces_only_one_new_login(runtime):
    hass, _, api, _ = runtime
    channel = Air352MobileChannel(
        hass, api, "synthetic-account", AsyncMock(), AsyncMock()
    )
    channel._async_publish_account_bind = AsyncMock()
    await channel._async_reauthenticate_and_bind()
    await channel._async_reauthenticate_and_bind()
    api.authenticate.assert_awaited_once_with(force=True)
    channel._async_publish_account_bind.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_setup_releases_background_resources(runtime):
    hass, entry, _, _ = runtime
    failed = SimpleNamespace(
        async_setup=AsyncMock(),
        async_config_entry_first_refresh=AsyncMock(),
        async_start_push=AsyncMock(),
        async_shutdown=AsyncMock(),
    )
    with (
        patch("custom_components.air352.Air352Coordinator", return_value=failed),
        patch("custom_components.air352.Air352ApiClient"),
        patch("custom_components.air352.async_get_clientsession"),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            side_effect=RuntimeError("platform failed"),
        ),
        pytest.raises(RuntimeError),
    ):
        await async_setup_entry(hass, entry)
    failed.async_shutdown.assert_awaited_once()
    assert entry.entry_id not in hass.data["air352"]


def client():
    return Air352ApiClient(Mock(), "synthetic-account", "synthetic-password")


@pytest.mark.asyncio
async def test_concurrent_expired_requests_share_one_authentication():
    api = client()

    async def authenticate():
        await asyncio.sleep(0)
        api._iot_token = "synthetic-new-token"
        api._iot_token_ts = __import__("time").time()
        api._iot_token_expire = 72000

    api._authenticate = AsyncMock(side_effect=authenticate)
    await asyncio.gather(*(api.ensure_authenticated() for _ in range(8)))
    api._authenticate.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_authentication_refreshes_a_locally_valid_session():
    api = client()
    api._iot_token = "synthetic-rejected-token"
    api._iot_token_ts = __import__("time").time()
    api._iot_token_expire = 72000
    api._authenticate = AsyncMock()
    await api.ensure_authenticated()
    api._authenticate.assert_not_awaited()
    await api.authenticate(force=True)
    api._authenticate.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_failed_authentication_is_rate_limited_then_recovers():
    api = client()
    api._authenticate = AsyncMock(side_effect=Air352ConnectionError("offline"))
    results = await asyncio.gather(
        *(api.ensure_authenticated() for _ in range(8)), return_exceptions=True
    )
    assert all(isinstance(r, Air352ConnectionError) for r in results)
    api._authenticate.assert_awaited_once()
    api._auth_retry_after = 0
    api._authenticate.side_effect = None
    await api.authenticate()
    assert api._authenticate.await_count == 2
    assert api._auth_failure is None


@pytest.mark.asyncio
async def test_bootstrap_auth_error_cannot_recursively_login():
    api = client()
    api._request_json = AsyncMock(
        return_value={"code": 401, "message": "invalid token"}
    )
    api.authenticate = AsyncMock()
    with pytest.raises(Air352AuthError):
        await api._ali_gw_request("/account/createSessionByAuthCode", {})
    api.authenticate.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_service_timeout_does_not_invalidate_credentials():
    api = client()
    api._iot_token = "synthetic-current-token"
    api._request_json = AsyncMock(
        return_value={"code": 500, "message": "session service timeout"}
    )
    api.authenticate = AsyncMock()
    with pytest.raises(Air352ApiError):
        await api._ali_gw_request("/thing/properties/get", {}, iot_token=api._iot_token)
    api.authenticate.assert_not_awaited()
    assert api._iot_token == "synthetic-current-token"


@pytest.mark.asyncio
async def test_late_old_token_failure_does_not_overwrite_new_session():
    api = client()
    api._iot_token = "synthetic-new-token"
    api._iot_token_ts = __import__("time").time()
    api._iot_token_expire = 72000
    api._request_json = AsyncMock(
        side_effect=[
            {"code": 401, "message": "invalid token"},
            {"code": 200, "data": {}},
        ]
    )
    api._authenticate = AsyncMock()
    await api._ali_gw_request(
        "/thing/properties/get", {}, iot_token="synthetic-old-token"
    )
    api._authenticate.assert_not_awaited()
    assert api._iot_token == "synthetic-new-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["login", "oauth"])
async def test_server_errors_are_not_bad_credentials(stage):
    api = client()
    api._request_json = AsyncMock(
        return_value={"code": 500, "message": "gateway timeout"}
    )
    with pytest.raises(Air352ApiError):
        if stage == "login":
            await api.authenticate()
        else:
            await api._ali_oa_login("synthetic-access-token")


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"<html>service unavailable</html>", b"[]"])
async def test_non_json_or_invalid_payload_becomes_connection_error(content):
    response = Mock()
    response.read = AsyncMock(return_value=content)
    cm = AsyncMock()
    cm.__aenter__.return_value = response
    api = client()
    api._session.request.return_value = cm
    with pytest.raises(Air352ConnectionError):
        await api._request_json("POST", "https://synthetic.invalid/api")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_transport_failure_becomes_connection_error(failure):
    cm = AsyncMock()
    cm.__aenter__.side_effect = failure
    api = client()
    api._session.request.return_value = cm
    with pytest.raises(Air352ConnectionError):
        await api._request_json("POST", "https://synthetic.invalid/api")


@pytest.mark.asyncio
async def test_compressed_gateway_response_is_supported():
    response = Mock()
    response.read = AsyncMock(return_value=gzip.compress(b'{"code":200}'))
    cm = AsyncMock()
    cm.__aenter__.return_value = response
    api = client()
    api._session.request.return_value = cm
    assert await api._request_json("POST", "https://synthetic.invalid/api") == {
        "code": 200
    }
