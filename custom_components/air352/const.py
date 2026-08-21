from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


DOMAIN = "air352"
MANUFACTURER = "352"

APPID_352 = "8d5018f2bc0f11ea8e6388e9fe5ac5b6"
BASE_URL_352 = "https://app.352air.com"

ALI_APP_KEY = "27554844"
ALI_APP_SECRET = "b66d2c9767cd15a7c5a088341055d134"
ALI_DOMAIN = "api.link.aliyun.com"
ALI_OA_DOMAIN = "living-account.cn-shanghai.aliyuncs.com"

DEFAULT_SCAN_INTERVAL = 10
ACTIVE_PROPERTY_REFRESH_INTERVAL = 60
ACTIVE_PROPERTY_REFRESH_SETTLE_SECONDS = 2

CONF_IOT_TOKEN = "iot_token"
CONF_IOT_REFRESH_TOKEN = "iot_refresh_token"
CONF_IOT_TOKEN_EXPIRE = "iot_token_expire"

DEVICE_TYPE_AIR = "AirPurifier"
DEVICE_TYPE_HUMIDIFIER = "Humidifier"
DEVICE_TYPE_PURIFIER = "WaterPurifier"

Z120_PRODUCT_KEY = "a10n269QEvP"
Z120_REFRESH_PROPERTY = "ResearchAllProperty"
Z120_REFRESH_VALUE = "1"

Z120_MODEL_PATTERN = re.compile(r"(?<![A-Z0-9])Z120(?![A-Z0-9])", re.IGNORECASE)

Z120_INVALID_SENSOR_VALUES: dict[str, tuple[Any, ...]] = {
    "PM25": (65535, "65535"),
    "PM10": (65535, "65535"),
    "AAL": (255, "255"),
    "CurrentTemperature": (327.6, 327.67, "327.6", "327.67"),
    "RelativeHumidity": (327.6, 327.67, "327.6", "327.67"),
}

CATEGORY_KEY_ALIASES = {
    DEVICE_TYPE_AIR.lower(): DEVICE_TYPE_AIR,
    DEVICE_TYPE_HUMIDIFIER.lower(): DEVICE_TYPE_HUMIDIFIER,
    DEVICE_TYPE_PURIFIER.lower(): DEVICE_TYPE_PURIFIER,
}


def normalize_device_category(category_key: str | None) -> str:
    """Normalize API categoryKey values to the integration's canonical names."""
    if not category_key:
        return ""
    category = str(category_key)
    return CATEGORY_KEY_ALIASES.get(category.lower(), category)


def resolve_product_key(
    device: Mapping[str, Any],
    device_info: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve a product key, including Z120 records with missing or unknown keys."""
    info = device_info or {}
    product_keys = (device.get("productKey"), info.get("productKey"))
    if Z120_PRODUCT_KEY in product_keys:
        return Z120_PRODUCT_KEY
    product_key = next((value for value in product_keys if value), None)

    category_key = device.get("categoryKey") or info.get("categoryKey")
    if category_key and normalize_device_category(str(category_key)) != DEVICE_TYPE_AIR:
        return str(product_key) if product_key is not None else None

    for source in (device, info):
        for field in ("productModel", "productName"):
            value = source.get(field)
            if value is not None and Z120_MODEL_PATTERN.search(str(value)):
                return Z120_PRODUCT_KEY

    return str(product_key) if product_key is not None else None


def is_invalid_sensor_value(
    property_key: str,
    value: Any,
    product_key: str | None,
) -> bool:
    """Return whether a Z120 cloud value is a known no-data sentinel."""
    return (
        product_key == Z120_PRODUCT_KEY
        and value in Z120_INVALID_SENSOR_VALUES.get(property_key, ())
    )
