"""Sensor platform for Rclone Backup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import RcloneBackupCoordinator, RcloneConfigEntry
from .entity import RcloneBackupEntity
from .models import RcloneStatusData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RcloneSensorEntityDescription(SensorEntityDescription):
    """Describe an Rclone Backup sensor."""

    value_fn: Callable[[RcloneStatusData], StateType]
    attributes_fn: (
        Callable[[RcloneBackupCoordinator, RcloneStatusData], dict[str, Any]] | None
    ) = None
    available_fn: Callable[[RcloneStatusData], bool] = lambda data: True


def _status_attributes(
    coordinator: RcloneBackupCoordinator, data: RcloneStatusData
) -> dict[str, Any]:
    quota = data.quota
    attrs: dict[str, Any] = {
        "backup_path": coordinator.client.backup_path,
        "endpoint_url": coordinator.client.base_url,
        "rc_available": data.rc_available,
        "rclone_version": data.version,
        "backups_count": data.backups_count,
        "backups_size_bytes": data.backups_size,
        "latest_backup_name": data.latest_backup_name,
        "latest_backup_date": data.latest_backup_date,
    }
    if quota is not None:
        attrs.update(
            {
                "storage_total_bytes": quota.total,
                "storage_used_bytes": quota.used,
                "storage_free_bytes": quota.free,
                "storage_trashed_bytes": quota.trashed,
                "storage_other_bytes": quota.other,
                "storage_free_percent": quota.free_percent,
                "storage_total_tb": (
                    round(quota.total / (1024**4), 2)
                    if quota.total is not None
                    else None
                ),
                "storage_free_tb": (
                    round(quota.free / (1024**4), 2) if quota.free is not None else None
                ),
                "storage_used_tb": (
                    round(quota.used / (1024**4), 2) if quota.used is not None else None
                ),
            }
        )
    return attrs


SENSOR_DESCRIPTIONS: tuple[RcloneSensorEntityDescription, ...] = (
    RcloneSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=["connected", "low_space", "unavailable"],
        value_fn=lambda data: data.status,
        attributes_fn=_status_attributes,
    ),
    RcloneSensorEntityDescription(
        key="storage_total",
        translation_key="storage_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda data: (
            data.quota is not None and data.quota.total is not None
        ),
        value_fn=lambda data: data.quota.total if data.quota else None,
    ),
    RcloneSensorEntityDescription(
        key="storage_used",
        translation_key="storage_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda data: (
            data.quota is not None and data.quota.used is not None
        ),
        value_fn=lambda data: data.quota.used if data.quota else None,
    ),
    RcloneSensorEntityDescription(
        key="storage_free",
        translation_key="storage_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.TERABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda data: (
            data.quota is not None and data.quota.free is not None
        ),
        value_fn=lambda data: data.quota.free if data.quota else None,
    ),
    RcloneSensorEntityDescription(
        key="storage_trashed",
        translation_key="storage_trashed",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda data: (
            data.quota is not None and data.quota.trashed is not None
        ),
        value_fn=lambda data: data.quota.trashed if data.quota else None,
    ),
    RcloneSensorEntityDescription(
        key="storage_free_percent",
        translation_key="storage_free_percent",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_fn=lambda data: (
            data.quota is not None and data.quota.free_percent is not None
        ),
        value_fn=lambda data: data.quota.free_percent if data.quota else None,
    ),
    RcloneSensorEntityDescription(
        key="backups_size",
        translation_key="backups_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.backups_size,
    ),
    RcloneSensorEntityDescription(
        key="backups_count",
        translation_key="backups_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.backups_count,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RcloneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Rclone Backup sensor entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        RcloneBackupSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class RcloneBackupSensor(RcloneBackupEntity, SensorEntity):
    """Sensor exposing Rclone storage pool quota and HA backup stats."""

    entity_description: RcloneSensorEntityDescription

    def __init__(
        self,
        coordinator: RcloneBackupCoordinator,
        description: RcloneSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return whether entity data is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.entity_description.available_fn(self.coordinator.data)
        )

    @property
    def native_value(self) -> StateType:
        """Return sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extended pool status attributes when defined."""
        if (
            self.coordinator.data is None
            or self.entity_description.attributes_fn is None
        ):
            return None
        return self.entity_description.attributes_fn(
            self.coordinator, self.coordinator.data
        )
