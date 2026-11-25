"""Binary sensor platform for Rclone Backup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RcloneBackupCoordinator, RcloneConfigEntry
from .entity import RcloneBackupEntity
from .models import RcloneStatusData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RcloneBinarySensorDescription(BinarySensorEntityDescription):
    """Describe an Rclone Backup binary sensor."""

    is_on_fn: Callable[[RcloneBackupCoordinator, RcloneStatusData], bool]


BINARY_SENSOR_DESCRIPTIONS: tuple[RcloneBinarySensorDescription, ...] = (
    RcloneBinarySensorDescription(
        key="connectivity",
        translation_key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda coordinator, _data: coordinator.last_update_success,
    ),
    RcloneBinarySensorDescription(
        key="low_space",
        translation_key="low_space",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda coordinator, data: (
            data.quota is not None
            and data.quota.free_percent is not None
            and coordinator.low_space_threshold > 0
            and data.quota.free_percent < coordinator.low_space_threshold
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RcloneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Rclone Backup binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        RcloneBackupBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class RcloneBackupBinarySensor(RcloneBackupEntity, BinarySensorEntity):
    """Binary sensor for Rclone connectivity and low space warnings."""

    entity_description: RcloneBinarySensorDescription

    def __init__(
        self,
        coordinator: RcloneBackupCoordinator,
        description: RcloneBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return true when the condition holds."""
        if self.coordinator.data is None:
            return False if self.entity_description.key == "connectivity" else None
        return self.entity_description.is_on_fn(self.coordinator, self.coordinator.data)
