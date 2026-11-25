"""Diagnostics support for Rclone Backup."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import RcloneConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: RcloneConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for an Rclone Backup config entry."""
    coordinator = entry.runtime_data
    status = asdict(coordinator.data) if coordinator.data else None
    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "status": status,
        "last_update_success": coordinator.last_update_success,
    }
