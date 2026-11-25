"""Constants for the Rclone Backup integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from homeassistant.util.hass_dict import HassKey

if TYPE_CHECKING:
    from .coordinator import RcloneBackupCoordinator

DOMAIN: Final = "rclone_backup"
ATTRIBUTION: Final = "Data provided by Rclone WebDAV & RC API"

CONF_BACKUP_PATH: Final = "backup_path"
CONF_RC_ENABLED: Final = "rc_enabled"
CONF_RC_PATH: Final = "rc_path"
CONF_REMOTE_NAME: Final = "remote_name"
CONF_LOW_SPACE_THRESHOLD: Final = "low_space_threshold"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_NAME: Final = "Rclone Backup"
DEFAULT_BACKUP_PATH: Final = "/backups/homeassistant"
DEFAULT_RC_ENABLED: Final = True
DEFAULT_RC_PATH: Final = "/rc"
DEFAULT_REMOTE_NAME: Final = ""
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_SCAN_INTERVAL: Final = 300
DEFAULT_LOW_SPACE_THRESHOLD: Final = 10

UPLOAD_TIMEOUT_SECONDS: Final = 21600
REQUEST_TIMEOUT_SECONDS: Final = 60

DATA_BACKUP_AGENT_LISTENERS: HassKey[list[Callable[[], None]]] = HassKey(
    f"{DOMAIN}.backup_agent_listeners"
)
DATA_COORDINATOR_MAP: HassKey[dict[str, RcloneBackupCoordinator]] = HassKey(
    f"{DOMAIN}.coordinators"
)
