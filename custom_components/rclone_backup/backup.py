"""Backup platform for Rclone Backup."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any, override

from homeassistant.components.backup import (
    AgentBackup,
    BackupAgent,
    BackupAgentError,
    BackupNotFound,
    OnProgressCallback,
    suggested_filename,
)
from homeassistant.core import HomeAssistant, callback

from .api import RcloneError, RcloneNotFoundError
from .const import DATA_BACKUP_AGENT_LISTENERS, DATA_COORDINATOR_MAP, DOMAIN
from .coordinator import RcloneBackupCoordinator

LOGGER = logging.getLogger(__name__)


async def async_get_backup_agents(
    hass: HomeAssistant,
) -> list[BackupAgent]:
    """Return active Rclone backup agents."""
    coordinators = hass.data.get(DATA_COORDINATOR_MAP, {})
    return [RcloneBackupAgent(coordinator) for coordinator in coordinators.values()]


@callback
def async_register_backup_agents_listener(
    hass: HomeAssistant,
    *,
    listener: Callable[[], None],
    **kwargs: Any,
) -> Callable[[], None]:
    """Register a listener notified when backup agents are added or removed."""
    listeners = hass.data.setdefault(DATA_BACKUP_AGENT_LISTENERS, [])
    listeners.append(listener)

    @callback
    def remove_listener() -> None:
        if listener in listeners:
            listeners.remove(listener)

    return remove_listener


@callback
def async_notify_backup_listeners(hass: HomeAssistant) -> None:
    """Notify Home Assistant Backup manager about agent availability changes."""
    for listener in list(hass.data.get(DATA_BACKUP_AGENT_LISTENERS) or ()):
        listener()


class RcloneBackupAgent(BackupAgent):
    """Home Assistant BackupAgent backed by Rclone WebDAV & RC."""

    domain = DOMAIN

    def __init__(self, coordinator: RcloneBackupCoordinator) -> None:
        """Initialize the backup agent."""
        super().__init__()
        self._coordinator = coordinator
        self.name = coordinator.config_entry.title
        self.unique_id = coordinator.config_entry.entry_id

    @override
    async def async_upload_backup(
        self,
        *,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        backup: AgentBackup,
        on_progress: OnProgressCallback,
        **kwargs: Any,
    ) -> None:
        """Stream backup archive and sidecar metadata to Rclone WebDAV."""
        raw_name = suggested_filename(backup)
        base_name = raw_name.removesuffix(".tar")
        tar_name = f"{base_name}.tar"
        meta_name = f"{base_name}.metadata.json"
        meta_bytes = json.dumps(backup.as_dict()).encode("utf-8")

        try:
            await self._coordinator.client.async_ensure_directory()
            await self._coordinator.client.async_upload_stream(
                tar_name, open_stream, on_progress=on_progress
            )
            await self._coordinator.client.async_write_bytes(meta_name, meta_bytes)
        except RcloneError as err:
            raise BackupAgentError(
                f"Failed to upload backup {backup.backup_id}: {err}"
            ) from err

        self._coordinator.register_uploaded_backup(backup, tar_name, meta_name)
        await self._coordinator.async_request_refresh()

    @override
    async def async_list_backups(self, **kwargs: Any) -> list[AgentBackup]:
        """List backups stored in the configured Rclone WebDAV path."""
        try:
            items = await self._coordinator.async_list_cached_backups()
        except RcloneError as err:
            raise BackupAgentError(f"Failed to list backups: {err}") from err
        return [backup for backup, _, _ in items]

    @override
    async def async_get_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AgentBackup:
        """Return backup metadata for a specific backup_id."""
        backup, _, _ = await self._resolve_backup(backup_id)
        return backup

    @override
    async def async_download_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """Stream a backup archive back to Home Assistant."""
        _, tar_name, _ = await self._resolve_backup(backup_id)
        try:
            return await self._coordinator.client.async_open_download_stream(tar_name)
        except RcloneNotFoundError as err:
            raise BackupNotFound(f"Backup {backup_id} not found") from err
        except RcloneError as err:
            raise BackupAgentError(
                f"Failed to download backup {backup_id}: {err}"
            ) from err

    @override
    async def async_delete_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> None:
        """Delete backup archive and metadata sidecar from Rclone WebDAV."""
        _, tar_name, meta_name = await self._resolve_backup(backup_id)
        try:
            await self._coordinator.client.async_delete(tar_name)
            try:
                await self._coordinator.client.async_delete(meta_name)
            except RcloneNotFoundError:
                LOGGER.debug("Metadata file %s already removed", meta_name)
        except RcloneNotFoundError as err:
            self._coordinator.invalidate_backup(backup_id)
            raise BackupNotFound(f"Backup {backup_id} not found") from err
        except RcloneError as err:
            raise BackupAgentError(
                f"Failed to delete backup {backup_id}: {err}"
            ) from err

        self._coordinator.invalidate_backup(backup_id)
        await self._coordinator.async_request_refresh()

    async def _resolve_backup(self, backup_id: str) -> tuple[AgentBackup, str, str]:
        try:
            items = await self._coordinator.async_list_cached_backups()
        except RcloneError as err:
            raise BackupAgentError(f"Failed to query backups: {err}") from err

        for item in items:
            if item[0].backup_id == backup_id:
                return item
        raise BackupNotFound(f"Backup {backup_id} not found")
