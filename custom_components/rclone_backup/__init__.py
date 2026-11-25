"""The Rclone Backup integration."""

from __future__ import annotations

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import RcloneApiClient
from .backup import async_notify_backup_listeners
from .const import (
    CONF_BACKUP_PATH,
    CONF_RC_ENABLED,
    CONF_RC_PATH,
    CONF_REMOTE_NAME,
    DATA_COORDINATOR_MAP,
    DEFAULT_BACKUP_PATH,
    DEFAULT_RC_ENABLED,
    DEFAULT_RC_PATH,
    DEFAULT_REMOTE_NAME,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import RcloneBackupCoordinator, RcloneConfigEntry
from .repairs import async_clear_repair_issues
from .services import SERVICE_REFRESH, async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Rclone Backup domain services."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RcloneConfigEntry) -> bool:
    """Set up Rclone Backup from a config entry."""
    await async_setup_services(hass)

    verify_ssl = bool(entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = RcloneApiClient(
        session=session,
        base_url=entry.data[CONF_URL],
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
        backup_path=entry.data.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH),
        rc_enabled=bool(entry.data.get(CONF_RC_ENABLED, DEFAULT_RC_ENABLED)),
        rc_path=entry.data.get(CONF_RC_PATH, DEFAULT_RC_PATH),
        remote_name=str(entry.data.get(CONF_REMOTE_NAME, DEFAULT_REMOTE_NAME)),
    )

    coordinator = RcloneBackupCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    coordinators = hass.data.setdefault(DATA_COORDINATOR_MAP, {})
    coordinators[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_notify_backup_listeners(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RcloneConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinators = hass.data.get(DATA_COORDINATOR_MAP, {})
        coordinators.pop(entry.entry_id, None)
        async_clear_repair_issues(hass, entry.entry_id)
        async_notify_backup_listeners(hass)
        if not coordinators and hass.services.has_service(DOMAIN, SERVICE_REFRESH):
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: RcloneConfigEntry) -> None:
    """Reload config entry when options or config change."""
    await hass.config_entries.async_reload(entry.entry_id)
