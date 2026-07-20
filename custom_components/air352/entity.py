from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .coordinator import Air352Coordinator


async def async_set_device_properties(
    coordinator: Air352Coordinator,
    iot_id: str,
    values: dict[str, int],
) -> None:
    """Set cloud properties and surface command failures as HA errors."""
    try:
        await coordinator.api.set_device_properties(iot_id, values)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError("Failed to update 352 device") from err
