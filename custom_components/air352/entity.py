from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .coordinator import Air352Coordinator


async def async_set_device_properties(
    coordinator: Air352Coordinator,
    iot_id: str,
    values: dict[str, int],
    *,
    optimistic_values: dict[str, int] | None = None,
) -> None:
    """Set cloud properties and surface command failures as HA errors."""
    try:
        coordinator_setter = getattr(
            coordinator,
            "async_set_device_properties",
            None,
        )
        if coordinator_setter is not None:
            await coordinator_setter(
                iot_id,
                values,
                optimistic_values=optimistic_values,
            )
            return

        await coordinator.api.set_device_properties(iot_id, values)
    except HomeAssistantError:
        raise
    except Exception as err:
        raise HomeAssistantError("Failed to update 352 device") from err

    optimistic = optimistic_values or values
    properties = coordinator.data.setdefault(iot_id, {})
    for key, value in optimistic.items():
        prop = properties.get(key)
        if isinstance(prop, dict):
            prop["value"] = value
        else:
            properties[key] = {"value": value}
    coordinator.async_set_updated_data(coordinator.data)
