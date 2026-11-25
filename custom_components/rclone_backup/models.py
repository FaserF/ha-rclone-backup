"""Data models for the Rclone Backup integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RcloneQuotaData:
    """Storage quota metrics returned by Rclone RC `/operations/about`."""

    total: int | None
    used: int | None
    free: int | None
    trashed: int | None
    other: int | None = None

    @property
    def free_percent(self) -> float | None:
        """Return remaining free percentage relative to total storage."""
        if self.total is None or self.free is None or self.total <= 0:
            return None
        return round((self.free / self.total) * 100.0, 2)


@dataclass(frozen=True, slots=True)
class RcloneStatusData:
    """Snapshot state exposed by the Rclone Backup coordinator."""

    quota: RcloneQuotaData | None
    backups_count: int
    backups_size: int
    latest_backup_date: str | None
    latest_backup_name: str | None
    rc_available: bool
    version: str | None
    status: str
    last_error: str | None = None
