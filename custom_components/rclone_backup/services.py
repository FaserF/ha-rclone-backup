"""Service registration for Rclone Backup."""

from __future__ import annotations

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DATA_COORDINATOR_MAP, DOMAIN

SERVICE_REFRESH = "refresh"

SERVICE_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain services."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def _handle_refresh(call: ServiceCall) -> None:
        coordinators = hass.data.get(DATA_COORDINATOR_MAP, {})
        target_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if target_id:
            coord = coordinators.get(target_id)
            if coord is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="entry_not_found",
                    translation_placeholders={"entry_id": target_id},
                )
            await coord.async_refresh()
            return

        for coord in coordinators.values():
            await coord.async_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        _handle_refresh,
        schema=SERVICE_REFRESH_SCHEMA,
    )
