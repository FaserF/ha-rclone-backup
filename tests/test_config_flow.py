"""Tests for Rclone Backup config, reauth, reconfigure, and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone_backup.api import (
    RcloneAuthError,
    RcloneConnectionError,
)
from custom_components.rclone_backup.const import DOMAIN

from .conftest import MOCK_CONFIG_DATA


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch(
            "custom_components.rclone_backup.config_flow.RcloneApiClient",
            autospec=True,
        ) as mock_cls,
        patch(
            "custom_components.rclone_backup.async_setup_entry",
            return_value=True,
        ),
    ):
        mock_cls.return_value.async_check_connection = AsyncMock(return_value=None)
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_CONFIG_DATA
        )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Rclone Backup"
    assert result2["data"][CONF_URL] == "https://rclone.example.invalid"


async def test_user_flow_errors_and_recovery(hass: HomeAssistant) -> None:
    """Test invalid_auth, cannot_connect, and recovery."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.rclone_backup.config_flow.RcloneApiClient",
        autospec=True,
    ) as mock_cls:
        mock_cls.return_value.async_check_connection = AsyncMock(
            side_effect=RcloneAuthError("401")
        )
        res_auth = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_CONFIG_DATA
        )
        assert res_auth["type"] is FlowResultType.FORM
        assert res_auth["errors"] == {"base": "invalid_auth"}

        mock_cls.return_value.async_check_connection = AsyncMock(
            side_effect=RcloneConnectionError("timeout")
        )
        res_conn = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=MOCK_CONFIG_DATA
        )
        assert res_conn["type"] is FlowResultType.FORM
        assert res_conn["errors"] == {"base": "cannot_connect"}

        mock_cls.return_value.async_check_connection = AsyncMock(return_value=None)
        with patch(
            "custom_components.rclone_backup.async_setup_entry",
            return_value=True,
        ):
            res_ok = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input=MOCK_CONFIG_DATA
            )
        assert res_ok["type"] is FlowResultType.CREATE_ENTRY


async def test_reauth_and_reconfigure_and_options(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test reauthentication, reconfiguration, and options flows."""
    mock_config_entry.add_to_hass(hass)

    reauth_init = await mock_config_entry.start_reauth_flow(hass)
    assert reauth_init["type"] is FlowResultType.FORM
    assert reauth_init["step_id"] == "reauth_confirm"

    with (
        patch(
            "custom_components.rclone_backup.config_flow.RcloneApiClient",
            autospec=True,
        ) as mock_cls,
        patch(
            "custom_components.rclone_backup.async_setup_entry",
            return_value=True,
        ),
    ):
        mock_cls.return_value.async_check_connection = AsyncMock(return_value=None)
        reauth_done = await hass.config_entries.flow.async_configure(
            reauth_init["flow_id"],
            user_input={
                CONF_USERNAME: "new-user",
                CONF_PASSWORD: "new-password",
                CONF_VERIFY_SSL: True,
            },
        )
    assert reauth_done["type"] is FlowResultType.ABORT
    assert reauth_done["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_USERNAME] == "new-user"

    reconf_init = await mock_config_entry.start_reconfigure_flow(hass)
    assert reconf_init["type"] is FlowResultType.FORM
    with (
        patch(
            "custom_components.rclone_backup.config_flow.RcloneApiClient",
            autospec=True,
        ) as mock_cls,
        patch(
            "custom_components.rclone_backup.async_setup_entry",
            return_value=True,
        ),
    ):
        mock_cls.return_value.async_check_connection = AsyncMock(return_value=None)
        reconf_done = await hass.config_entries.flow.async_configure(
            reconf_init["flow_id"],
            user_input={**MOCK_CONFIG_DATA, CONF_USERNAME: "reconf-user"},
        )
    assert reconf_done["type"] is FlowResultType.ABORT
    assert reconf_done["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_USERNAME] == "reconf-user"

    opt_init = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert opt_init["type"] is FlowResultType.FORM
    opt_done = await hass.config_entries.options.async_configure(
        opt_init["flow_id"],
        user_input={"scan_interval": 120, "low_space_threshold": 15},
    )
    assert opt_done["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        "scan_interval": 120,
        "low_space_threshold": 15,
    }
