"""Repair issue management for Rclone Backup."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .models import RcloneStatusData

ISSUE_CONNECTION_FAILED = "connection_failed"
ISSUE_LOW_STORAGE = "low_storage"


def async_sync_repair_issues(
    hass: HomeAssistant,
    entry_id: str,
    entry_title: str,
    status: RcloneStatusData | None,
    low_space_threshold_pct: int,
    connection_error: str | None = None,
) -> None:
    """Create or clear repair issues based on current Rclone health and quota."""
    conn_issue_id = f"{ISSUE_CONNECTION_FAILED}_{entry_id}"
    space_issue_id = f"{ISSUE_LOW_STORAGE}_{entry_id}"

    if connection_error:
        ir.async_create_issue(
            hass,
            DOMAIN,
            conn_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_CONNECTION_FAILED,
            translation_placeholders={
                "name": entry_title,
                "error": connection_error,
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, conn_issue_id)

    free_pct = status.quota.free_percent if status and status.quota else None
    if (
        free_pct is not None
        and low_space_threshold_pct > 0
        and free_pct < low_space_threshold_pct
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            space_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_LOW_STORAGE,
            translation_placeholders={
                "name": entry_title,
                "free_percent": f"{free_pct:.1f}",
                "threshold": str(low_space_threshold_pct),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, space_issue_id)


def async_clear_repair_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove all repair issues associated with a config entry."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_CONNECTION_FAILED}_{entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_LOW_STORAGE}_{entry_id}")
