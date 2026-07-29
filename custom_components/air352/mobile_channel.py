"""Aliyun mobile MQTT channel used by the official 352 app."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import ssl
from typing import Awaitable, Callable

from homeassistant.core import HomeAssistant
import paho.mqtt.client as mqtt

from .api import Air352ApiClient
from .mobile_protocol import (
    MobileMqttSettings,
    build_account_bind_payload,
    build_mqtt_settings,
    decode_downstream_message,
    mobile_device_sn,
)


_LOGGER = logging.getLogger(__name__)
CONNECT_TIMEOUT = 15
CA_CERTIFICATE = Path(__file__).with_name("root.crt")

MessageHandler = Callable[[str, dict], Awaitable[None]]
StateHandler = Callable[[bool], Awaitable[None]]


class Air352MobileChannel:
    """Maintain the account-bound mobile push connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Air352ApiClient,
        username: str,
        message_handler: MessageHandler,
        state_handler: StateHandler,
    ) -> None:
        self._hass = hass
        self._api = api
        self._username = username
        self._message_handler = message_handler
        self._state_handler = state_handler
        self._client: mqtt.Client | None = None
        self._settings: MobileMqttSettings | None = None
        self._ready = asyncio.Event()
        self._stopping = False
        self._bound = False
        self._reauthenticating = False
        self._bind_reauth_attempted = False

    @property
    def connected(self) -> bool:
        """Return whether MQTT is connected and the account is bound."""
        return self._bound

    async def async_start(self) -> bool:
        """Start the channel and wait briefly for the initial account bind."""
        triple = await self._api.get_mobile_channel_credentials(
            mobile_device_sn(self._username)
        )
        self._settings = build_mqtt_settings(triple)

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._settings.client_id,
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(
            self._settings.username,
            self._settings.password,
        )
        await self._hass.async_add_executor_job(
            client.tls_set,
            str(CA_CERTIFICATE),
            None,
            None,
            ssl.CERT_REQUIRED,
        )
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        self._client = client

        client.connect_async(
            self._settings.host,
            port=self._settings.port,
            keepalive=60,
        )
        client.loop_start()

        try:
            await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT)
        except TimeoutError:
            _LOGGER.warning(
                "352 official-app push channel is still reconnecting; "
                "REST polling remains active"
            )
            return False
        return True

    async def async_stop(self) -> None:
        """Stop the channel and its network thread."""
        self._stopping = True
        client = self._client
        self._client = None
        if client is None:
            return
        await self._hass.async_add_executor_job(client.disconnect)
        await self._hass.async_add_executor_job(client.loop_stop)
        self._bound = False

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        reason_code,
        properties,
    ) -> None:
        if reason_code != 0:
            _LOGGER.warning(
                "352 mobile MQTT connection failed: %s", reason_code
            )
            return
        settings = self._settings
        if settings is None:
            return
        self._bind_reauth_attempted = False
        result, _mid = client.subscribe(
            [(topic, 1) for topic in settings.downstream_topics]
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.warning(
                "352 mobile MQTT subscribe failed: %s", result
            )

    def _on_subscribe(
        self,
        client: mqtt.Client,
        userdata,
        mid,
        reason_codes,
        properties,
    ) -> None:
        if any(getattr(code, "is_failure", False) for code in reason_codes):
            _LOGGER.warning(
                "352 mobile MQTT topic rejected: %s", reason_codes
            )
            return
        self._schedule_task(self._async_publish_account_bind)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata,
        message: mqtt.MQTTMessage,
    ) -> None:
        settings = self._settings
        if settings is None:
            return
        decoded = decode_downstream_message(
            settings,
            message.topic,
            message.payload,
        )
        if decoded is None:
            return
        path, payload = decoded
        if path == "account/bind_reply":
            if payload.get("code") == 200:
                self._schedule_task(self._async_mark_bound)
            else:
                _LOGGER.warning(
                    "352 mobile account bind failed: code=%s message=%s",
                    payload.get("code"),
                    payload.get("message"),
                )
                self._schedule_task(self._async_reauthenticate_and_bind)
            return
        self._schedule_task(self._message_handler, path, payload)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ) -> None:
        if self._stopping:
            return
        _LOGGER.warning(
            "352 official-app push channel disconnected: %s", reason_code
        )
        self._schedule_task(self._async_mark_disconnected)

    async def _async_publish_account_bind(self) -> None:
        client = self._client
        settings = self._settings
        if client is None or settings is None:
            return
        try:
            await self._api.ensure_authenticated()
            payload = build_account_bind_payload(
                settings,
                self._api.iot_token,
            )
        except Exception:
            _LOGGER.exception(
                "Failed to prepare 352 mobile account bind"
            )
            return
        info = client.publish(
            settings.account_bind_topic,
            payload,
            qos=1,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.warning(
                "352 mobile account bind publish failed: %s", info.rc
            )

    async def _async_reauthenticate_and_bind(self) -> None:
        if (
            self._reauthenticating
            or self._bind_reauth_attempted
            or self._stopping
        ):
            return
        self._reauthenticating = True
        self._bind_reauth_attempted = True
        try:
            await self._api.authenticate()
            await self._async_publish_account_bind()
        except Exception:
            _LOGGER.exception(
                "Failed to refresh the 352 mobile account binding"
            )
        finally:
            self._reauthenticating = False

    async def _async_mark_bound(self) -> None:
        was_bound = self._bound
        self._bound = True
        self._ready.set()
        if not was_bound:
            _LOGGER.info("352 official-app push channel connected")
            await self._state_handler(True)

    async def _async_mark_disconnected(self) -> None:
        was_bound = self._bound
        self._bound = False
        if was_bound:
            await self._state_handler(False)

    def _schedule_task(self, function, *args) -> None:
        if self._stopping:
            return

        def create_task() -> None:
            self._hass.async_create_task(function(*args))

        self._hass.loop.call_soon_threadsafe(create_task)
