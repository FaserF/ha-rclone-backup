"""Tests for RcloneApiClient WebDAV and RC JSON calls."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.rclone_backup.api import (
    RcloneApiClient,
    RcloneAuthError,
    RcloneConnectionError,
    RcloneNotFoundError,
    _parse_propfind_files,
)


def test_parse_propfind_files_filters_collections() -> None:
    """Verify PROPFIND XML parsing extracts files and ignores directories."""
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <D:multistatus xmlns:D="DAV:">
      <D:response>
        <D:href>/backups/homeassistant/</D:href>
        <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
      </D:response>
      <D:response>
        <D:href>/backups/homeassistant/Test%20Backup.tar</D:href>
        <D:propstat><D:prop><D:resourcetype/><D:getcontentlength>4096</D:getcontentlength></D:prop></D:propstat>
      </D:response>
      <D:response>
        <D:href>/backups/homeassistant/subdir/</D:href>
        <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
      </D:response>
    </D:multistatus>"""
    parsed = _parse_propfind_files(xml, "/backups/homeassistant")
    assert parsed == {"Test Backup.tar": 4096}


def test_parse_propfind_rejects_doctype() -> None:
    """Reject DTD/ENTITY payloads to prevent XML entity expansion."""
    unsafe = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY bar "baz">]><D:multistatus xmlns:D="DAV:"/>'
    with pytest.raises(RcloneConnectionError):
        _parse_propfind_files(unsafe, "/backups")


async def test_api_client_operations(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify RC quota, PROPFIND, MKCOL, PUT, GET stream, and DELETE."""
    base = "https://rclone.example.invalid"
    aioclient_mock.post(
        f"{base}/rc/operations/about",
        json={"total": 1000, "used": 250, "free": 750, "trashed": 10},
    )
    aioclient_mock.post(f"{base}/rc/core/version", json={"version": "v1.69.1"})
    aioclient_mock.request(
        "PROPFIND",
        f"{base}/backups/",
        status=207,
        text='<D:multistatus xmlns:D="DAV:"/>',
    )
    aioclient_mock.request("PROPFIND", f"{base}/backups/ha/", status=404)
    aioclient_mock.request("MKCOL", f"{base}/backups/ha/", status=201)
    aioclient_mock.put(f"{base}/backups/ha/meta.json", status=201)
    aioclient_mock.request(
        "PROPFIND",
        f"{base}/backups/ha/",
        status=207,
        text='<D:multistatus xmlns:D="DAV:"/>',
    )
    aioclient_mock.get(f"{base}/backups/ha/test.tar", content=b"hello-backup")
    aioclient_mock.delete(f"{base}/backups/ha/test.tar", status=204)
    aioclient_mock.get(f"{base}/backups/ha/missing.tar", status=404)

    api = RcloneApiClient(
        async_get_clientsession(hass),
        base,
        username="ha",
        password="pw",
        backup_path="/backups/ha",
    )

    quota = await api.async_check_connection()
    assert quota is not None
    assert quota.total == 1000
    assert quota.free_percent == 75.0
    assert await api.async_get_version() == "v1.69.1"
    await api.async_write_bytes("meta.json", b"{}")

    dl_stream = await api.async_open_download_stream("test.tar")
    assert b"".join([c async for c in dl_stream]) == b"hello-backup"

    await api.async_delete("test.tar")

    with pytest.raises(RcloneNotFoundError):
        await api.async_read_text("missing.tar")

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{base}/rc/operations/about", status=401)
    with pytest.raises(RcloneAuthError):
        await api.async_get_quota()


async def test_upload_stream_progress() -> None:
    """Verify async_upload_stream iterates stream chunks and calls on_progress."""
    captured: list[bytes] = []
    progress: list[int] = []

    class _FakeResp:
        status = 201

        async def __aenter__(self) -> _FakeResp:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _FakeSession:
        def put(self, _url: str, *, data, headers, timeout):
            self._data = data
            assert headers["Authorization"].startswith("Basic ")
            assert timeout is not None
            return _FakePutCtx(data)

    class _FakePutCtx:
        def __init__(self, gen) -> None:
            self._gen = gen

        async def __aenter__(self) -> _FakeResp:
            async for chunk in self._gen:
                captured.append(chunk)
            return _FakeResp()

        async def __aexit__(self, *_args: object) -> None:
            return None

    api = RcloneApiClient(
        _FakeSession(),  # type: ignore[arg-type]
        "https://rclone.example.invalid",
        username="ha",
        password="pw",
        backup_path="/backups/ha",
    )

    async def _opener():
        async def _gen():
            yield b"hello-"
            yield b"backup"

        return _gen()

    written = await api.async_upload_stream(
        "test.tar",
        _opener,
        on_progress=lambda *, bytes_uploaded: progress.append(bytes_uploaded),
    )
    assert written == 12
    assert b"".join(captured) == b"hello-backup"
    assert progress == [6, 12]
