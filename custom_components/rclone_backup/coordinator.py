"""DataUpdateCoordinator for Rclone Backup."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.backup import AgentBackup
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RcloneApiClient, RcloneAuthError, RcloneError
from .const import (
    CONF_LOW_SPACE_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOW_SPACE_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import RcloneStatusData
from .repairs import async_sync_repair_issues

if TYPE_CHECKING:
    type RcloneConfigEntry = ConfigEntry[RcloneBackupCoordinator]
else:
    type RcloneConfigEntry = ConfigEntry

LOGGER = logging.getLogger(__name__)


class RcloneBackupCoordinator(DataUpdateCoordinator[RcloneStatusData]):
    """Coordinate Rclone quota, backup inventory, and health status."""

    config_entry: RcloneConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: RcloneConfigEntry,
        client: RcloneApiClient,
    ) -> None:
        """Initialize coordinator."""
        scan_seconds = int(
            config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(seconds=max(60, scan_seconds)),
            always_update=False,
        )
        self.client = client
        self._meta_cache: dict[str, tuple[AgentBackup, str, str]] = {}
        self._last_files: dict[str, int] = {}

    @property
    def low_space_threshold(self) -> int:
        """Return configured low free storage percentage warning threshold."""
        return int(
            self.config_entry.options.get(
                CONF_LOW_SPACE_THRESHOLD, DEFAULT_LOW_SPACE_THRESHOLD
            )
        )

    async def async_list_cached_backups(
        self, *, force_refresh: bool = False
    ) -> list[tuple[AgentBackup, str, str]]:
        """List remote HA backups with incremental metadata caching."""
        files = await self.client.async_list_files()
        self._last_files = files

        meta_files = {
            name: size
            for name, size in files.items()
            if name.endswith(".metadata.json")
        }
        if force_refresh:
            self._meta_cache.clear()

        # Drop deleted entries from cache
        active_backup_ids: set[str] = set()
        results: list[tuple[AgentBackup, str, str]] = []

        # Keep reverse index by metadata filename for quick hit lookup
        by_meta_name = {
            meta_name: (backup, tar_name, meta_name)
            for backup, tar_name, meta_name in self._meta_cache.values()
        }

        for meta_name in sorted(meta_files):
            base_name = meta_name.removesuffix(".metadata.json")
            tar_name = f"{base_name}.tar"
            if tar_name not in files and base_name in files:
                tar_name = base_name
            elif tar_name not in files:
                continue

            cached = by_meta_name.get(meta_name)
            if cached is not None:
                results.append(cached)
                active_backup_ids.add(cached[0].backup_id)
                continue

            try:
                raw_meta = await self.client.async_read_text(meta_name)
                backup = AgentBackup.from_dict(json.loads(raw_meta))
            except (RcloneError, ValueError, KeyError, TypeError) as exc:
                LOGGER.warning("Skipping invalid metadata file %s: %s", meta_name, exc)
                continue

            item = (backup, tar_name, meta_name)
            self._meta_cache[backup.backup_id] = item
            active_backup_ids.add(backup.backup_id)
            results.append(item)

        for stale_id in list(self._meta_cache):
            if stale_id not in active_backup_ids:
                self._meta_cache.pop(stale_id, None)

        return results

    def invalidate_backup(self, backup_id: str) -> None:
        """Invalidate a single cached backup entry."""
        self._meta_cache.pop(backup_id, None)

    def register_uploaded_backup(
        self, backup: AgentBackup, tar_name: str, meta_name: str
    ) -> None:
        """Store newly uploaded backup metadata directly in cache."""
        self._meta_cache[backup.backup_id] = (backup, tar_name, meta_name)

    async def _async_update_data(self) -> RcloneStatusData:
        """Poll WebDAV directory listing and optional Rclone RC quota."""
        try:
            backups = await self.async_list_cached_backups()
            quota = await self.client.async_get_quota()
            version = await self.client.async_get_version()
        except RcloneAuthError as err:
            async_sync_repair_issues(
                self.hass,
                self.config_entry.entry_id,
                self.config_entry.title,
                None,
                self.low_space_threshold,
                connection_error=str(err),
            )
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"url": self.config_entry.data[CONF_URL]},
            ) from err
        except RcloneError as err:
            async_sync_repair_issues(
                self.hass,
                self.config_entry.entry_id,
                self.config_entry.title,
                None,
                self.low_space_threshold,
                connection_error=str(err),
            )
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="connection_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        backups_size = sum(
            self._last_files.get(tar_name, 0) + self._last_files.get(meta_name, 0)
            for _, tar_name, meta_name in backups
        )
        sorted_backups = sorted(backups, key=lambda item: item[0].date, reverse=True)
        latest_backup = sorted_backups[0][0] if sorted_backups else None

        status_label = "connected"
        if quota and quota.free_percent is not None:
            if quota.free_percent < self.low_space_threshold:
                status_label = "low_space"

        status = RcloneStatusData(
            quota=quota,
            backups_count=len(backups),
            backups_size=backups_size,
            latest_backup_date=latest_backup.date if latest_backup else None,
            latest_backup_name=latest_backup.name if latest_backup else None,
            rc_available=quota is not None,
            version=version,
            status=status_label,
        )
        async_sync_repair_issues(
            self.hass,
            self.config_entry.entry_id,
            self.config_entry.title,
            status,
            self.low_space_threshold,
        )
        return status
