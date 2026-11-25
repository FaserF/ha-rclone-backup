"""Async client for Rclone WebDAV and RC JSON APIs."""

from __future__ import annotations

import base64
import posixpath
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any
from urllib.parse import quote, unquote, urlparse

import aiohttp
from homeassistant.components.backup import OnProgressCallback
from homeassistant.helpers.aiohttp_client import ChunkAsyncStreamIterator

from .const import REQUEST_TIMEOUT_SECONDS, UPLOAD_TIMEOUT_SECONDS
from .models import RcloneQuotaData


class RcloneError(Exception):
    """Base error for Rclone Backup client operations."""


class RcloneAuthError(RcloneError):
    """Authentication or authorization error (401/403)."""


class RcloneConnectionError(RcloneError):
    """Network, TLS, or upstream availability error."""


class RcloneNotFoundError(RcloneError):
    """Target file or collection was not found (404)."""


class _ResponseStreamIterator(AsyncIterator[bytes]):
    """Async iterator wrapping an open aiohttp response stream."""

    def __init__(self, response: aiohttp.ClientResponse) -> None:
        self._response = response
        self._chunk_iter = ChunkAsyncStreamIterator(response.content)
        self._closed = False

    def __aiter__(self) -> _ResponseStreamIterator:
        return self

    async def __anext__(self) -> bytes:
        try:
            return await self._chunk_iter.__anext__()
        except StopAsyncIteration:
            self.close()
            raise
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Release underlying HTTP response when iteration stops."""
        if not self._closed:
            self._closed = True
            self._response.release()


def _normalize_subpath(path: str) -> str:
    cleaned = "/" + "/".join(part for part in path.split("/") if part and part != ".")
    return cleaned if cleaned != "/" else "/"


def _normalize_rc_prefix(rc_path: str) -> str:
    stripped = "/".join(part for part in rc_path.split("/") if part)
    return f"/{stripped}" if stripped else ""


class RcloneApiClient:
    """Client combining WebDAV file operations with optional Rclone RC telemetry."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        backup_path: str = "/backups/homeassistant",
        rc_enabled: bool = True,
        rc_path: str = "/rc",
        remote_name: str = "",
    ) -> None:
        """Initialize the Rclone client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._backup_path = _normalize_subpath(backup_path)
        self._rc_enabled = rc_enabled
        self._rc_prefix = _normalize_rc_prefix(rc_path)
        self._remote_name = remote_name.strip()
        self._resolved_remote: str | None = None
        self._auth_header: str | None = None
        if username:
            token = base64.b64encode(f"{username}:{password or ''}".encode()).decode(
                "ascii"
            )
            self._auth_header = f"Basic {token}"

    @property
    def base_url(self) -> str:
        """Return normalized server base URL."""
        return self._base_url

    @property
    def backup_path(self) -> str:
        """Return normalized backup directory path."""
        return self._backup_path

    def _webdav_url(self, filename: str | None = None) -> str:
        base_dir = (
            "" if self._backup_path == "/" else quote(self._backup_path, safe="/")
        )
        if filename:
            safe_name = quote(filename.lstrip("/"), safe="")
            return f"{self._base_url}{base_dir}/{safe_name}"
        return f"{self._base_url}{base_dir}/"

    def _rc_url(self, command: str) -> str:
        cmd = command.lstrip("/")
        return f"{self._base_url}{self._rc_prefix}/{cmd}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: Any = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[int, dict[str, str], bytes]:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        req_headers = dict(headers) if headers else {}
        if self._auth_header:
            req_headers.setdefault("Authorization", self._auth_header)
        try:
            async with self._session.request(
                method,
                url,
                headers=req_headers or None,
                data=data,
                json=json_body,
                timeout=timeout,
            ) as resp:
                body = await resp.read()
                resp_headers = dict(resp.headers)
                if resp.status in (401, 403):
                    raise RcloneAuthError(
                        f"Authentication failed ({resp.status}) on {method} {url}"
                    )
                return resp.status, resp_headers, body
        except RcloneAuthError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RcloneConnectionError(
                f"Connection failed for {method} {url}: {exc}"
            ) from exc

    async def async_ensure_directory(self) -> None:
        """Ensure target backup directory exists recursively via MKCOL."""
        if self._backup_path == "/":
            status, _, _ = await self._request(
                "PROPFIND", self._webdav_url(), headers={"Depth": "0"}
            )
            if status not in (200, 207):
                raise RcloneConnectionError(
                    f"WebDAV root check failed with HTTP {status}"
                )
            return

        segments = [seg for seg in self._backup_path.split("/") if seg]
        current = ""
        for seg in segments:
            current = f"{current}/{seg}"
            seg_url = f"{self._base_url}{quote(current, safe='/')}/"
            status, _, _ = await self._request(
                "PROPFIND", seg_url, headers={"Depth": "0"}
            )
            if status in (200, 207):
                continue
            if status in (404, 405, 409):
                mk_status, _, _ = await self._request("MKCOL", seg_url)
                if mk_status not in (200, 201, 204, 301, 405):
                    raise RcloneConnectionError(
                        f"Failed to create directory {current} (HTTP {mk_status})"
                    )
                continue
            raise RcloneConnectionError(
                f"Unexpected HTTP {status} probing directory {current}"
            )

    async def async_check_connection(self) -> RcloneQuotaData | None:
        """Verify WebDAV reachability/credentials and optionally fetch RC quota."""
        await self.async_ensure_directory()
        if not self._rc_enabled:
            return None
        return await self.async_get_quota()

    async def _resolve_rc_fs(self) -> str | None:
        if self._remote_name:
            return (
                self._remote_name
                if self._remote_name.endswith(":")
                else f"{self._remote_name}:"
            )
        if self._resolved_remote:
            return self._resolved_remote
        status, _, body = await self._request(
            "POST", self._rc_url("config/listremotes"), json_body={}
        )
        if status != 200:
            return None
        try:
            import json

            remotes = json.loads(body.decode("utf-8")).get("remotes") or []
            if remotes:
                first = str(remotes[0])
                self._resolved_remote = first if first.endswith(":") else f"{first}:"
                return self._resolved_remote
        except (ValueError, UnicodeDecodeError):
            return None
        return None

    async def async_get_quota(self) -> RcloneQuotaData | None:
        """Query Rclone RC `/operations/about` JSON API for pool quota metrics."""
        if not self._rc_enabled:
            return None

        target_fs = self._remote_name or self._resolved_remote or ""
        req_body: dict[str, Any] = (
            {"fs": target_fs if target_fs.endswith(":") else f"{target_fs}:"}
            if target_fs
            else {}
        )
        status, _, body = await self._request(
            "POST", self._rc_url("operations/about"), json_body=req_body
        )
        if status == 400 and not target_fs:
            discovered = await self._resolve_rc_fs()
            if discovered:
                status, _, body = await self._request(
                    "POST",
                    self._rc_url("operations/about"),
                    json_body={"fs": discovered},
                )
        if status in (400, 404, 405, 501):
            return None
        if status >= 400:
            raise RcloneConnectionError(
                f"Rclone RC operations/about failed with HTTP {status}"
            )
        try:
            import json

            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RcloneConnectionError(
                f"Invalid JSON from Rclone RC operations/about: {exc}"
            ) from exc

        return RcloneQuotaData(
            total=_to_int_or_none(payload.get("total")),
            used=_to_int_or_none(payload.get("used")),
            free=_to_int_or_none(payload.get("free")),
            trashed=_to_int_or_none(payload.get("trashed")),
            other=_to_int_or_none(payload.get("other")),
        )

    async def async_get_version(self) -> str | None:
        """Query Rclone RC `/core/version` for Rclone server version string."""
        if not self._rc_enabled:
            return None
        status, _, body = await self._request(
            "POST", self._rc_url("core/version"), json_body={}
        )
        if status != 200:
            return None
        try:
            import json

            payload = json.loads(body.decode("utf-8"))
            ver = payload.get("version")
            return str(ver) if ver else None
        except (ValueError, UnicodeDecodeError):
            return None

    async def async_list_files(self) -> dict[str, int]:
        """List non-directory filenames and byte sizes in the backup folder."""
        propfind_xml = (
            '<?xml version="1.0" encoding="utf-8" ?>'
            '<D:propfind xmlns:D="DAV:">'
            "<D:prop><D:resourcetype/><D:getcontentlength/></D:prop>"
            "</D:propfind>"
        )
        status, _, body = await self._request(
            "PROPFIND",
            self._webdav_url(),
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            data=propfind_xml.encode("utf-8"),
        )
        if status == 404:
            await self.async_ensure_directory()
            return {}
        if status not in (200, 207):
            raise RcloneConnectionError(
                f"WebDAV PROPFIND listing failed with HTTP {status}"
            )
        return _parse_propfind_files(body, self._backup_path)

    async def async_read_text(self, filename: str) -> str:
        """Download a UTF-8 file (e.g. `.metadata.json`) from the backup folder."""
        url = self._webdav_url(filename)
        status, _, body = await self._request("GET", url)
        if status == 404:
            raise RcloneNotFoundError(f"Remote file not found: {filename}")
        if status >= 400:
            raise RcloneConnectionError(f"GET {filename} failed with HTTP {status}")
        return body.decode("utf-8")

    async def async_write_bytes(self, filename: str, content: bytes) -> None:
        """Upload raw bytes (e.g. metadata sidecar) via WebDAV PUT."""
        url = self._webdav_url(filename)
        status, _, _ = await self._request(
            "PUT",
            url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=content,
        )
        if status not in (200, 201, 204):
            raise RcloneConnectionError(f"PUT {filename} failed with HTTP {status}")

    async def async_upload_stream(
        self,
        filename: str,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        on_progress: OnProgressCallback | None = None,
    ) -> int:
        """Stream backup archive bytes directly to WebDAV PUT with progress reporting."""
        url = self._webdav_url(filename)
        uploaded = 0

        async def _chunk_generator() -> AsyncIterator[bytes]:
            nonlocal uploaded
            stream = await open_stream()
            async for chunk in stream:
                if not chunk:
                    continue
                uploaded += len(chunk)
                if on_progress is not None:
                    on_progress(bytes_uploaded=uploaded)
                yield chunk

        timeout = aiohttp.ClientTimeout(total=UPLOAD_TIMEOUT_SECONDS, sock_read=300)
        put_headers = {"Content-Type": "application/octet-stream"}
        if self._auth_header:
            put_headers["Authorization"] = self._auth_header
        try:
            async with self._session.put(
                url,
                data=_chunk_generator(),
                headers=put_headers,
                timeout=timeout,
            ) as resp:
                if resp.status in (401, 403):
                    raise RcloneAuthError(
                        f"Authentication failed ({resp.status}) uploading {filename}"
                    )
                if resp.status not in (200, 201, 204):
                    text = await resp.text()
                    raise RcloneConnectionError(
                        f"WebDAV PUT {filename} failed ({resp.status}): {text[:200]}"
                    )
        except (RcloneAuthError, RcloneConnectionError):
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RcloneConnectionError(
                f"Upload stream failed for {filename}: {exc}"
            ) from exc
        return uploaded

    async def async_open_download_stream(self, filename: str) -> AsyncIterator[bytes]:
        """Open a streamed GET response and return an AsyncIterator[bytes]."""
        url = self._webdav_url(filename)
        timeout = aiohttp.ClientTimeout(total=UPLOAD_TIMEOUT_SECONDS, sock_read=300)
        get_headers = (
            {"Authorization": self._auth_header} if self._auth_header else None
        )
        try:
            resp = await self._session.get(url, headers=get_headers, timeout=timeout)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise RcloneConnectionError(
                f"Download stream failed for {filename}: {exc}"
            ) from exc

        if resp.status in (401, 403):
            resp.release()
            raise RcloneAuthError(
                f"Authentication failed ({resp.status}) downloading {filename}"
            )
        if resp.status == 404:
            resp.release()
            raise RcloneNotFoundError(f"Remote file not found: {filename}")
        if resp.status >= 400:
            resp.release()
            raise RcloneConnectionError(
                f"WebDAV GET {filename} failed with HTTP {resp.status}"
            )
        return _ResponseStreamIterator(resp)

    async def async_delete(self, filename: str) -> None:
        """Delete a file from the backup folder via WebDAV DELETE."""
        url = self._webdav_url(filename)
        status, _, _ = await self._request("DELETE", url)
        if status == 404:
            raise RcloneNotFoundError(f"Remote file not found: {filename}")
        if status not in (200, 202, 204):
            raise RcloneConnectionError(f"DELETE {filename} failed with HTTP {status}")


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_propfind_files(xml_bytes: bytes, target_dir: str) -> dict[str, int]:
    """Safely parse WebDAV PROPFIND multistatus XML without DTD/entity expansion."""
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise RcloneConnectionError("Rejected unsafe XML payload from WebDAV server")
    try:
        root = ET.fromstring(xml_bytes)  # noqa: S314
    except ET.ParseError as exc:
        raise RcloneConnectionError(f"Malformed WebDAV PROPFIND XML: {exc}") from exc

    target_norm = target_dir.rstrip("/") or "/"
    files: dict[str, int] = {}
    for resp_el in root.findall(".//{DAV:}response"):
        href_el = resp_el.find("{DAV:}href")
        if href_el is None or not href_el.text:
            continue
        parsed_path = unquote(urlparse(href_el.text).path)
        if parsed_path.rstrip("/") == target_norm.rstrip("/") or parsed_path.endswith(
            "/"
        ):
            continue
        if resp_el.find(".//{DAV:}resourcetype/{DAV:}collection") is not None:
            continue
        filename = posixpath.basename(parsed_path)
        if not filename:
            continue
        size_el = resp_el.find(".//{DAV:}getcontentlength")
        size = _to_int_or_none(size_el.text if size_el is not None else None) or 0
        files[filename] = size
    return files
