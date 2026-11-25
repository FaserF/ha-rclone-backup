"""Base entity class for Rclone Backup."""

from __future__ import annotations

from homeassistant.const import CONF_URL
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH, DOMAIN
from .coordinator import RcloneBackupCoordinator


class RcloneBackupEntity(CoordinatorEntity[RcloneBackupCoordinator]):
    """Base entity representing an Rclone Backup endpoint."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: RcloneBackupCoordinator, key: str) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        backup_path = entry.data.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Rclone",
            model=f"Encrypted WebDAV ({backup_path})",
            configuration_url=entry.data.get(CONF_URL),
            entry_type=DeviceEntryType.SERVICE,
            sw_version=coordinator.data.version if coordinator.data else None,
        )
