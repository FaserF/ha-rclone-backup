"""Tests for Rclone Backup coordinator, sensors, repairs, and diagnostics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from homeassistant.components.backup import AgentBackup, Folder, suggested_filename
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone_backup.api import RcloneConnectionError
from custom_components.rclone_backup.const import DOMAIN
from custom_components.rclone_backup.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.rclone_backup.models import RcloneQuotaData

from .conftest import MOCK_QUOTA


async def test_sensors_diagnostics_repairs_and_button(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_rclone_client: AsyncMock,
) -> None:
    """Verify pool status, quota sensors, attributes, diagnostics, and repairs."""
    backup = AgentBackup(
        addons=[],
        backup_id="bk001",
        date="2026-11-25T10:00:00+00:00",
        database_included=True,
        extra_metadata={},
        folders=[Folder.SHARE],
        homeassistant_included=True,
        homeassistant_version="2026.10.4",
        name="Full Nightly",
        protected=True,
        size=1048576,
    )
    base = suggested_filename(backup).removesuffix(".tar")
    mock_rclone_client.async_list_files = AsyncMock(
        return_value={f"{base}.tar": 1048576, f"{base}.metadata.json": 256}
    )
    mock_rclone_client.async_read_text = AsyncMock(
        return_value=json.dumps(backup.as_dict())
    )
    mock_rclone_client.async_get_quota = AsyncMock(return_value=MOCK_QUOTA)

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    status_state = hass.states.get("sensor.rclone_backup_pool_status")
    assert status_state is not None
    assert status_state.state == "connected"
    assert status_state.attributes["backups_count"] == 1
    assert status_state.attributes["backups_size_bytes"] == 1048832
    assert status_state.attributes["storage_total_bytes"] == MOCK_QUOTA.total
    assert status_state.attributes["latest_backup_name"] == "Full Nightly"

    conn_state = hass.states.get("binary_sensor.rclone_backup_connection")
    assert conn_state is not None
    assert conn_state.state == "on"

    low_space = hass.states.get("binary_sensor.rclone_backup_low_storage_space")
    assert low_space is not None
    assert low_space.state == "off"

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diag["entry"]["data"]["password"] == "**REDACTED**"
    assert diag["status"]["backups_count"] == 1

    # Simulate low storage space (<10% threshold -> 5%)
    mock_rclone_client.async_get_quota = AsyncMock(
        return_value=RcloneQuotaData(total=1000, used=950, free=50, trashed=0)
    )
    await hass.services.async_call(
        DOMAIN,
        "refresh",
        {"config_entry_id": mock_config_entry.entry_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.rclone_backup_pool_status").state == "low_space"
    assert (
        hass.states.get("binary_sensor.rclone_backup_low_storage_space").state == "on"
    )
    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(
        DOMAIN, f"low_storage_{mock_config_entry.entry_id}"
    )

    # Simulate transient connection failure -> error repair created
    mock_rclone_client.async_get_quota = AsyncMock(
        side_effect=RcloneConnectionError("unreachable")
    )
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    await hass.async_block_till_done()
    assert issue_reg.async_get_issue(
        DOMAIN, f"connection_failed_{mock_config_entry.entry_id}"
    )

    # Unload cleans up repair issues
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert (
        issue_reg.async_get_issue(
            DOMAIN, f"connection_failed_{mock_config_entry.entry_id}"
        )
        is None
    )
