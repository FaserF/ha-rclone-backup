"""Shared fixtures for Rclone Backup tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone_backup.const import (
    CONF_BACKUP_PATH,
    CONF_RC_ENABLED,
    CONF_RC_PATH,
    DEFAULT_BACKUP_PATH,
    DEFAULT_RC_PATH,
    DOMAIN,
)
from custom_components.rclone_backup.models import RcloneQuotaData

MOCK_CONFIG_DATA = {
    CONF_NAME: "Rclone Backup",
    CONF_URL: "https://rclone.example.invalid",
    CONF_USERNAME: "backup-user",
    CONF_PASSWORD: "super-secret-password",
    CONF_BACKUP_PATH: DEFAULT_BACKUP_PATH,
    CONF_RC_ENABLED: True,
    CONF_RC_PATH: DEFAULT_RC_PATH,
    CONF_VERIFY_SSL: True,
}

MOCK_QUOTA = RcloneQuotaData(
    total=66_400_194_396_160,
    used=11_864_992_389_194,
    free=49_841_318_770_880,
    trashed=4_142_388_671_729,
    other=4_693_883_236_086,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations across all tests."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Create a mock Rclone Backup config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Rclone Backup",
        unique_id="https://rclone.example.invalid/backups/homeassistant",
        data=MOCK_CONFIG_DATA,
        options={"scan_interval": 300, "low_space_threshold": 10},
        entry_id="test_entry_123",
    )


@pytest.fixture
def mock_rclone_client() -> Generator[AsyncMock]:
    """Patch RcloneApiClient with default healthy responses."""
    with patch(
        "custom_components.rclone_backup.RcloneApiClient",
        autospec=True,
    ) as mock_cls:
        client = mock_cls.return_value
        client.base_url = "https://rclone.example.invalid"
        client.backup_path = "/backups/homeassistant"
        client.async_check_connection = AsyncMock(return_value=MOCK_QUOTA)
        client.async_ensure_directory = AsyncMock(return_value=None)
        client.async_get_quota = AsyncMock(return_value=MOCK_QUOTA)
        client.async_get_version = AsyncMock(return_value="v1.69.1")
        client.async_list_files = AsyncMock(return_value={})
        client.async_read_text = AsyncMock(return_value="{}")
        client.async_write_bytes = AsyncMock(return_value=None)
        client.async_upload_stream = AsyncMock(return_value=1024)
        client.async_open_download_stream = AsyncMock()
        client.async_delete = AsyncMock(return_value=None)
        yield client
