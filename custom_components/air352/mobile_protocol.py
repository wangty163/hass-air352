"""Protocol helpers for the Aliyun mobile persistent channel."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


MOBILE_CHANNEL_PORT = 1883
DOWNSTREAM_PATHS = (
    "account/bind_reply",
    "thing/properties",
    "thing/status",
    "thing/events",
)


@dataclass(frozen=True)
class MobileTriple:
    """Aliyun virtual-device credentials returned by aepauth."""

    product_key: str
    device_name: str
    device_secret: str


@dataclass(frozen=True)
class MobileMqttSettings:
    """Derived MQTT settings for an Aliyun virtual mobile client."""

    host: str
    port: int
    client_id: str
    username: str
    password: str
    plain_client_id: str
    topic_prefix: str

    @property
    def downstream_topics(self) -> tuple[str, ...]:
        """Return the exact topics accepted by the current broker ACL."""
        return tuple(
            f"{self.topic_prefix}/app/down/{path}" for path in DOWNSTREAM_PATHS
        )

    @property
    def account_bind_topic(self) -> str:
        """Return the account-bind publish topic."""
        return f"{self.topic_prefix}/app/up/account/bind"

    @property
    def account_bind_reply_topic(self) -> str:
        """Return the account-bind response topic."""
        return f"{self.topic_prefix}/app/down/account/bind_reply"


def mobile_device_sn(username: str) -> str:
    """Create a stable App-device identifier without embedding the username."""
    return hashlib.sha256(
        f"homeassistant-air352:{username}".encode()
    ).hexdigest()[:32]


def build_aepauth_auth_info(
    app_key: str,
    app_secret: str,
    device_sn: str,
    *,
    client_id: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, str]:
    """Build the authInfo object used by the official mobile SDK."""
    client_id = client_id or secrets.token_hex(4)
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    sign_text = (
        f"appKey{app_key}"
        f"clientId{client_id}"
        f"deviceSn{device_sn}"
        f"timestamp{timestamp}"
    )
    signature = hmac.new(
        app_secret.encode(), sign_text.encode(), hashlib.sha1
    ).hexdigest()
    return {
        "clientId": client_id,
        "deviceSn": device_sn,
        "timestamp": timestamp,
        "sign": signature,
    }


def build_mqtt_settings(
    triple: MobileTriple,
    *,
    timestamp_ms: int | None = None,
) -> MobileMqttSettings:
    """Derive the MQTT connection fields used by public-channel-mobile."""
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    plain_client_id = f"{triple.device_name}&{triple.product_key}"
    sign_text = (
        f"clientId{plain_client_id}"
        f"deviceName{triple.device_name}"
        f"productKey{triple.product_key}"
        f"timestamp{timestamp}"
    )
    password = hmac.new(
        triple.device_secret.encode(), sign_text.encode(), hashlib.sha1
    ).hexdigest().upper()
    return MobileMqttSettings(
        host=(
            f"{triple.product_key}."
            "iot-as-mqtt.cn-shanghai.aliyuncs.com"
        ),
        port=MOBILE_CHANNEL_PORT,
        client_id=(
            f"{plain_client_id}|securemode=2,"
            f"signmethod=hmacsha1,timestamp={timestamp}|"
        ),
        username=plain_client_id,
        password=password,
        plain_client_id=plain_client_id,
        topic_prefix=(
            f"/sys/{triple.product_key}/{triple.device_name}"
        ),
    )


def build_account_bind_payload(
    settings: MobileMqttSettings,
    iot_token: str,
    *,
    message_id: str = "1",
    timestamp_ms: int | None = None,
) -> str:
    """Build the exact account/bind RPC payload used by the mobile SDK."""
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    return json.dumps(
        {
            "id": message_id,
            "system": {"version": "1.0", "time": timestamp},
            "request": {"clientId": settings.plain_client_id},
            "params": {"iotToken": iot_token},
        },
        separators=(",", ":"),
    )


def decode_downstream_message(
    settings: MobileMqttSettings,
    topic: str,
    payload: bytes,
) -> tuple[str, dict[str, Any]] | None:
    """Validate and decode a mobile-channel downstream message."""
    prefix = f"{settings.topic_prefix}/app/down/"
    if not topic.startswith(prefix):
        return None
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return topic[len(prefix) :], data
