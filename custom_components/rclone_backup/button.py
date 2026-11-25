"""Button platform for Rclone Backup."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RcloneBackupCoordinator, RcloneConfigEntry
from .entity import RcloneBackupEntity

PARALLEL_UPDATES = 0

REFRESH_DESCRIPTION = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RcloneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Rclone Backup action buttons."""
    async_add_entities([RcloneRefreshButton(entry.runtime_data)])


class RcloneRefreshButton(RcloneBackupEntity, ButtonEntity):
    """Button triggering an immediate quota and backup inventory refresh."""

    entity_description = REFRESH_DESCRIPTION

    def __init__(self, coordinator: RcloneBackupCoordinator) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, REFRESH_DESCRIPTION.key)

    async def async_press(self) -> None:
        """Trigger immediate coordinator refresh."""
        await self.coordinator.async_refresh()
