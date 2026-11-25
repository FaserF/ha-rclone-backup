# Rclone Backup for Home Assistant

[![CI](https://github.com/FaserF/ha-rclone-backup/actions/workflows/ci.yml/badge.svg)](https://github.com/FaserF/ha-rclone-backup/actions/workflows/ci.yml)
[![Linter](https://github.com/FaserF/ha-rclone-backup/actions/workflows/linter.yml/badge.svg)](https://github.com/FaserF/ha-rclone-backup/actions/workflows/linter.yml)

Home Assistant custom integration providing a native **Backup Agent** backed by **Rclone WebDAV** with **Rclone RC JSON API** quota and health monitoring.

## Features

- **Home Assistant Backup Agent (`rclone_backup`):** Streaming upload (`on_progress`), metadata sidecar (`.metadata.json`), listing, streaming restore download, and deletion over authenticated WebDAV.
- **Encrypted Cloud Pool Compatibility:** Designed for `rclone serve webdav <remote>: --rc` (including `crypt` remotes such as `cloud_pool_crypt:`), automatically creating missing target subdirectories via `MKCOL`.
- **Storage Quota & Status Sensors:**
  - `sensor.<name>_pool_status`: Primary status (`connected`, `low_space`, `unavailable`) with rich attributes (`storage_total_bytes`, `storage_used_bytes`, `storage_free_bytes`, `storage_trashed_bytes`, `storage_free_percent`, `backups_count`, `backups_size_bytes`, `latest_backup_name`, `latest_backup_date`, `rclone_version`, `backup_path`).
  - `sensor.<name>_storage_capacity`, `storage_used`, `storage_free`, `storage_trashed`, `storage_free_percentage` (`DATA_SIZE` / `%` diagnostic sensors).
  - `sensor.<name>_backups_total_size` and `backups_count`.
  - `binary_sensor.<name>_connection` and `low_storage_space` + `button.<name>_refresh_status`.
- **Repairs & Diagnostics:** Automatic HA Repair issues for unreachable/auth failures and low remaining pool space, plus redacted diagnostics and `rclone_backup.refresh` service.
- **Full Flow Coverage:** User config flow, reauthentication flow, reconfiguration flow, and options flow (`scan_interval`, `low_space_threshold`).

## Supported Targets

- Any Rclone instance launched with `rclone serve webdav <remote>: --user ... --pass ... --rc ...` (optionally reverse-proxied over TLS).
- Generic WebDAV servers (disable **Enable Rclone RC Quota & Version API** during setup to skip RC quota polling).

## Installation

### HACS (Custom Repository)

1. Add `https://github.com/FaserF/ha-rclone-backup` as a custom integration repository in HACS.
2. Install **Rclone Backup** and restart Home Assistant.
3. Add **Rclone Backup** under **Settings -> Devices & Services -> Add Integration**.

### Manual

Copy `custom_components/rclone_backup` to `/config/custom_components/rclone_backup` and restart Home Assistant.

## Configuration Parameters

| Parameter | Default | Description |
|---|---|---|
| `name` | `Rclone Backup` | Integration entry and device name. |
| `url` | — | Base HTTP/HTTPS URL serving WebDAV (and RC if enabled). |
| `username` / `password` | `""` | HTTP Basic Auth credentials. |
| `backup_path` | `/backups/homeassistant` | Subfolder in the WebDAV root where HA stores `.tar` and `.metadata.json` files. |
| `rc_enabled` | `true` | Poll Rclone RC `/operations/about` and `/core/version`. |
| `rc_path` | `/rc` | URL path prefix routed to Rclone RC. |
| `verify_ssl` | `true` | Validate TLS certificates. |

## Data Updates & Retention

- Coordinator polls every `300s` (configurable via Options: `60–3600s`).
- Low-space repair issue triggers below `10%` free pool space (configurable: `0–50%`, `0` disables).
- Backup retention is managed directly by Home Assistant's built-in Backup Scheduler.

## Troubleshooting

- **Auth failure (`invalid_auth`):** Reauthenticate cleanly via the Repair / Integration Reauth flow.
- **Generic WebDAV without RC:** Uncheck **Enable Rclone RC Quota & Version API** or verify your reverse proxy forwards `/rc/` to `rclone --rc-addr`.
- **Known Limitations:** Rclone RC storage quota metrics require Rclone `serve webdav ... --rc`. Remote listing reads `.metadata.json` sidecar files created by Home Assistant.

## Removal

1. Delete the **Rclone Backup** entry under **Settings -> Devices & Services**.
2. Uninstall via HACS or delete `/config/custom_components/rclone_backup` and restart Home Assistant.
