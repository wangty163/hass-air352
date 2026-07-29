from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "air352"),
)

from mobile_protocol import (  # noqa: E402
    MobileTriple,
    build_account_bind_payload,
    build_aepauth_auth_info,
    build_mqtt_settings,
    decode_downstream_message,
    mobile_device_sn,
)


class MobileProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.triple = MobileTriple(
            product_key="pk123",
            device_name="device456",
            device_secret="device-secret",
        )
        self.settings = build_mqtt_settings(
            self.triple,
            timestamp_ms=1_700_000_000_123,
        )

    def test_aepauth_matches_official_sdk_signature(self) -> None:
        auth_info = build_aepauth_auth_info(
            "12345678",
            "app-secret",
            "0123456789abcdef0123456789abcdef",
            client_id="a1b2c3d4",
            timestamp_ms=1_700_000_000_123,
        )

        self.assertEqual(
            auth_info,
            {
                "clientId": "a1b2c3d4",
                "deviceSn": "0123456789abcdef0123456789abcdef",
                "timestamp": "1700000000123",
                "sign": "eb86aed95c0d34e80b64d4c77206b75a2c3e7226",
            },
        )

    def test_mqtt_settings_match_official_sdk(self) -> None:
        self.assertEqual(
            self.settings.client_id,
            (
                "device456&pk123|securemode=2,"
                "signmethod=hmacsha1,timestamp=1700000000123|"
            ),
        )
        self.assertEqual(self.settings.username, "device456&pk123")
        self.assertEqual(
            self.settings.password,
            "513CC797D2AD12BADD50F6CFA2BA5230C367E9A5",
        )
        self.assertEqual(
            self.settings.downstream_topics,
            (
                "/sys/pk123/device456/app/down/account/bind_reply",
                "/sys/pk123/device456/app/down/thing/properties",
                "/sys/pk123/device456/app/down/thing/status",
                "/sys/pk123/device456/app/down/thing/events",
            ),
        )

    def test_account_bind_payload_and_downstream_decode(self) -> None:
        payload = build_account_bind_payload(
            self.settings,
            "iot-token",
            message_id="7",
            timestamp_ms=1_700_000_000_123,
        )
        self.assertEqual(
            json.loads(payload),
            {
                "id": "7",
                "system": {
                    "version": "1.0",
                    "time": "1700000000123",
                },
                "request": {"clientId": "device456&pk123"},
                "params": {"iotToken": "iot-token"},
            },
        )

        decoded = decode_downstream_message(
            self.settings,
            "/sys/pk123/device456/app/down/thing/properties",
            b'{"params":{"iotId":"iot-1","items":{"PowerSwitch":{"value":0}}}}',
        )
        self.assertEqual(
            decoded,
            (
                "thing/properties",
                {
                    "params": {
                        "iotId": "iot-1",
                        "items": {"PowerSwitch": {"value": 0}},
                    }
                },
            ),
        )

    def test_device_sn_is_stable_and_does_not_expose_username(self) -> None:
        first = mobile_device_sn("person@example.com")
        second = mobile_device_sn("person@example.com")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertNotIn("person", first)


if __name__ == "__main__":
    unittest.main()
