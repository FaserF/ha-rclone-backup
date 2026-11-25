"""Tests for Rclone Backup agent CRUD and streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.backup import (
    AgentBackup,
    BackupNotFound,
    Folder,
    suggested_filename,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone_backup.api import RcloneNotFoundError
from custom_components.rclone_backup.backup import (
    async_get_backup_agents,
    async_register_backup_agents_listener,
)


def _make_backup(backup_id: str = "abc123") -> AgentBackup:
    return AgentBackup(
        addons=[],
        backup_id=backup_id,
        date="2026-11-25T12:00:00+00:00",
        database_included=True,
        extra_metadata={},
        folders=[Folder.SHARE],
        homeassistant_included=True,
        homeassistant_version="2026.10.4",
        name="Nightly Encrypted Backup",
        protected=True,
        size=11,
    )


async def test_backup_agent_upload_list_download_delete(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_rclone_client: AsyncMock,
) -> None:
    """Verify full BackupAgent upload, list, get, download, and delete cycle."""
    mock_config_entry.add_to_hass(hass)
    listener_calls = 0

    def _on_change() -> None:
        nonlocal listener_calls
        listener_calls += 1

    unsub = async_register_backup_agents_listener(hass, listener=_on_change)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert listener_calls >= 1

    agents = await async_get_backup_agents(hass)
    assert len(agents) == 1
    agent = agents[0]
    assert agent.agent_id == f"rclone_backup.{mock_config_entry.entry_id}"

    backup = _make_backup("deadbeef")
    base = suggested_filename(backup)
    tar_name = f"{base}.tar"
    meta_name = f"{base}.metadata.json"

    async def _open_stream() -> AsyncIterator[bytes]:
        async def _gen() -> AsyncIterator[bytes]:
            yield b"tar-payload"

        return _gen()

    progress_values: list[int] = []

    def _on_progress(*, bytes_uploaded: int) -> None:
        progress_values.append(bytes_uploaded)

    async def _fake_upload(name: str, opener, on_progress=None) -> int:
        stream = await opener()
        data = b"".join([chunk async for chunk in stream])
        if on_progress:
            on_progress(bytes_uploaded=len(data))
        return len(data)

    mock_rclone_client.async_upload_stream = AsyncMock(side_effect=_fake_upload)
    await agent.async_upload_backup(
        open_stream=_open_stream, backup=backup, on_progress=_on_progress
    )
    assert progress_values == [11]
    mock_rclone_client.async_write_bytes.assert_awaited_once()

    # Remote listing
    mock_rclone_client.async_list_files = AsyncMock(
        return_value={tar_name: 11, meta_name: 200}
    )
    mock_rclone_client.async_read_text = AsyncMock(
        return_value=json.dumps(backup.as_dict())
    )
    listed = await agent.async_list_backups()
    assert [b.backup_id for b in listed] == ["deadbeef"]

    got = await agent.async_get_backup("deadbeef")
    assert got.name == "Nightly Encrypted Backup"

    async def _open_download(_filename: str) -> AsyncIterator[bytes]:
        async def _download_gen() -> AsyncIterator[bytes]:
            yield b"tar-"
            yield b"payload"

        return _download_gen()

    mock_rclone_client.async_open_download_stream = _open_download
    dl_stream = await agent.async_download_backup("deadbeef")
    downloaded = b"".join([chunk async for chunk in dl_stream])
    assert downloaded == b"tar-payload"

    await agent.async_delete_backup("deadbeef")
    assert mock_rclone_client.async_delete.await_count == 2

    mock_rclone_client.async_list_files = AsyncMock(return_value={})
    with pytest.raises(BackupNotFound):
        await agent.async_get_backup("missing-id")

    mock_rclone_client.async_delete = AsyncMock(side_effect=RcloneNotFoundError("404"))
    with pytest.raises(BackupNotFound):
        await agent.async_delete_backup("missing-id")

    unsub()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
