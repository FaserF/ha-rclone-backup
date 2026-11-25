"""Config flow for the Rclone Backup integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol  # type: ignore[no-redef]
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RcloneApiClient, RcloneAuthError, RcloneConnectionError
from .const import (
    CONF_BACKUP_PATH,
    CONF_LOW_SPACE_THRESHOLD,
    CONF_RC_ENABLED,
    CONF_RC_PATH,
    CONF_SCAN_INTERVAL,
    DEFAULT_BACKUP_PATH,
    DEFAULT_LOW_SPACE_THRESHOLD,
    DEFAULT_NAME,
    DEFAULT_RC_ENABLED,
    DEFAULT_RC_PATH,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

LOGGER = logging.getLogger(__name__)


def _build_user_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    src = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=src.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(CONF_URL, default=src.get(CONF_URL, "")): str,
            vol.Optional(CONF_USERNAME, default=src.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD, default=src.get(CONF_PASSWORD, "")): str,
            vol.Required(
                CONF_BACKUP_PATH,
                default=src.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH),
            ): str,
            vol.Required(
                CONF_RC_ENABLED,
                default=src.get(CONF_RC_ENABLED, DEFAULT_RC_ENABLED),
            ): bool,
            vol.Optional(
                CONF_RC_PATH, default=src.get(CONF_RC_PATH, DEFAULT_RC_PATH)
            ): str,
            vol.Required(
                CONF_VERIFY_SSL,
                default=src.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


def _normalize_unique_id(url: str, backup_path: str) -> str:
    clean_url = url.strip().rstrip("/").lower()
    clean_path = "/" + "/".join(p for p in backup_path.split("/") if p)
    return f"{clean_url}{clean_path}"


class RcloneBackupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Rclone Backup."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> RcloneBackupOptionsFlow:
        """Create the options flow."""
        return RcloneBackupOptionsFlow()

    async def _async_validate_input(self, user_input: dict[str, Any]) -> None:
        verify_ssl = bool(user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        client = RcloneApiClient(
            session=session,
            base_url=user_input[CONF_URL].strip(),
            username=user_input.get(CONF_USERNAME) or None,
            password=user_input.get(CONF_PASSWORD) or None,
            backup_path=user_input.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH),
            rc_enabled=bool(user_input.get(CONF_RC_ENABLED, DEFAULT_RC_ENABLED)),
            rc_path=user_input.get(CONF_RC_PATH, DEFAULT_RC_PATH),
        )
        await client.async_check_connection()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial setup step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = _normalize_unique_id(
                user_input[CONF_URL],
                user_input.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH),
            )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await self._async_validate_input(user_input)
            except RcloneAuthError:
                errors["base"] = "invalid_auth"
            except RcloneConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error during Rclone connection check")
                errors["base"] = "unknown"
            else:
                cleaned = {
                    **user_input,
                    CONF_URL: user_input[CONF_URL].strip().rstrip("/"),
                }
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data=cleaned,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_user_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication trigger."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reauthentication form submission."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            candidate = {**reauth_entry.data, **user_input}
            try:
                await self._async_validate_input(candidate)
            except RcloneAuthError:
                errors["base"] = "invalid_auth"
            except RcloneConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error during Rclone reauthentication")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates=user_input,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_USERNAME,
                        default=reauth_entry.data.get(CONF_USERNAME, ""),
                    ): str,
                    vol.Optional(CONF_PASSWORD, default=""): str,
                    vol.Required(
                        CONF_VERIFY_SSL,
                        default=reauth_entry.data.get(
                            CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
                        ),
                    ): bool,
                }
            ),
            description_placeholders={"url": reauth_entry.data.get(CONF_URL, "")},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of server URL, paths, or credentials."""
        reconf_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            new_unique = _normalize_unique_id(
                user_input[CONF_URL],
                user_input.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH),
            )
            await self.async_set_unique_id(new_unique)
            self._abort_if_unique_id_mismatch()

            try:
                await self._async_validate_input(user_input)
            except RcloneAuthError:
                errors["base"] = "invalid_auth"
            except RcloneConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error during Rclone reconfiguration")
                errors["base"] = "unknown"
            else:
                cleaned = {
                    **user_input,
                    CONF_URL: user_input[CONF_URL].strip().rstrip("/"),
                }
                return self.async_update_reload_and_abort(
                    reconf_entry,
                    data_updates=cleaned,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_user_schema(user_input or reconf_entry.data),
            errors=errors,
        )


class RcloneBackupOptionsFlow(OptionsFlowWithReload):
    """Handle Rclone Backup options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                    vol.Required(
                        CONF_LOW_SPACE_THRESHOLD,
                        default=self.config_entry.options.get(
                            CONF_LOW_SPACE_THRESHOLD, DEFAULT_LOW_SPACE_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
                }
            ),
        )
