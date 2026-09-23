"""Static resource path mapping and local file I/O.

Path铁律 master definition: 《后端技术栈与全局规范》二. All stored/returned
paths are relative `/static/...` paths; physical I/O always goes through the
single `resolve_static_path()` mapper which validates the four legal prefixes,
forbids `..`, and ensures the normalized path stays within `STATIC_ROOT`.
Illegal paths are rejected as `1002`.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image

from app.core.config import settings
from app.core.exceptions import InternalError, InvalidParamError

# Four legal path prefixes (穷举，不得新增) — see 《全局规范》二.2.
PREFIX_UPLOADS = "/static/uploads/"
PREFIX_GENERATED_POSTCARDS = "/static/generated/postcards/"
PREFIX_GENERATED_REPORTS = "/static/generated/reports/"
PREFIX_IMAGES = "/static/images/"
ALLOWED_PREFIXES = (
    PREFIX_UPLOADS,
    PREFIX_GENERATED_POSTCARDS,
    PREFIX_GENERATED_REPORTS,
    PREFIX_IMAGES,
)

DEFAULT_COVER_PATH = "/static/images/default_cover.jpg"

# Upload validation constants (safety limits, not business/deployment values).
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
EXTENSION_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
ALLOWED_MIME_TYPES = set(EXTENSION_TO_MIME.values())
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

# Moderate compression for uploads: cap the longest edge and re-encode lossy
# formats at a balanced quality. PNG stays lossless unless that exceeds the
# stored-file limit, when it falls back to WebP. These are storage safeguards.
UPLOAD_MAX_EDGE_PX = 2560
UPLOAD_JPEG_QUALITY = 90
UPLOAD_WEBP_QUALITY = 90


@dataclass
class StoredFile:
    """Result of persisting a binary file to the static tree."""

    relative_path: str
    abs_path: str
    mime_type: str
    size_bytes: int


def _static_root_abs() -> str:
    return os.path.abspath(settings.STATIC_ROOT)


def resolve_static_path(relative_path: str) -> str:
    """Map a `/static/...` relative path to a safe absolute physical path.

    Rejects anything that is not one of the four legal prefixes, contains
    `..`, or escapes `STATIC_ROOT` after normalization. Raises
    `InvalidParamError` (1002) on any violation.
    """
    if not isinstance(relative_path, str) or not relative_path:
        raise InvalidParamError("资源路径不合法")
    if "\\" in relative_path:
        # Normalize accidental backslashes to forward slashes for the check.
        relative_path = relative_path.replace("\\", "/")
    if ".." in relative_path:
        raise InvalidParamError("资源路径不合法：禁止 ..")
    if not any(relative_path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise InvalidParamError("资源路径不合法：前缀不在白名单内")

    static_root = _static_root_abs()
    # Strip the leading "/static/" and join under STATIC_ROOT.
    sub_path = relative_path[len("/static/"):]
    abs_path = os.path.abspath(os.path.join(static_root, sub_path))

    # Defense in depth: normalized path must remain inside STATIC_ROOT.
    if os.path.commonpath([abs_path, static_root]) != static_root:
        raise InvalidParamError("资源路径不合法：越权访问")
    return abs_path


def _year_month() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}", f"{now.month:02d}"


def build_relative_path(prefix: str, ext: str) -> str:
    """Build a `{prefix}{yyyy}/{mm}/{uuid}.{ext}` relative path."""
    ext = ext.lower().lstrip(".")
    yyyy, mm = _year_month()
    name = f"{uuid.uuid4().hex}.{ext}"
    return f"{prefix}{yyyy}/{mm}/{name}"


def build_upload_relative_path(ext: str) -> str:
    return build_relative_path(PREFIX_UPLOADS, ext)


def build_postcard_relative_path(ext: str) -> str:
    return build_relative_path(PREFIX_GENERATED_POSTCARDS, ext)


def build_report_cover_relative_path(ext: str) -> str:
    return build_relative_path(PREFIX_GENERATED_REPORTS, ext)


def build_plan_cover_relative_path(ext: str) -> str:
    """Store a plan-only trip cover under the existing images prefix."""
    return build_relative_path(PREFIX_IMAGES, ext)


def _ensure_parent_dir(abs_path: str) -> None:
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)


def _normalize_ext(filename: str | None, content_type: str | None) -> str:
    """Pick a safe extension from filename/content-type; validate allow-list."""
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS and content_type:
        for candidate_ext, mime in EXTENSION_TO_MIME.items():
            if mime == content_type:
                ext = candidate_ext
                break
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidParamError("文件类型不支持，仅允许 jpg/png/webp")
    return ext


def save_upload(content: bytes, filename: str | None, content_type: str | None) -> StoredFile:
    """Validate and persist an uploaded image with a backend-generated UUID name.

    Validates extension, MIME, size limit, and decodes via Pillow to confirm a
    real image. Returns a `StoredFile`. Raises `InvalidParamError` (1002) on
    validation failure, `InternalError` (1003) on disk failure.
    """
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise InvalidParamError("文件类型不支持，仅允许 jpg/png/webp")
    if len(content) == 0:
        raise InvalidParamError("文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidParamError("文件超过大小上限")

    ext = _normalize_ext(filename, content_type)

    # Decode to confirm a genuine, non-corrupt image.
    try:
        with Image.open(io.BytesIO(content)) as img:
            if img.width * img.height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
            img.verify()
    except Exception as exc:  # noqa: BLE001
        raise InvalidParamError("文件不是合法图片") from exc

    content, ext = _compress_image(content, ext)
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidParamError("图片压缩后仍超过大小上限")

    relative_path = build_upload_relative_path(ext)
    abs_path = resolve_static_path(relative_path)
    try:
        _ensure_parent_dir(abs_path)
        with open(abs_path, "wb") as fp:
            fp.write(content)
    except OSError as exc:
        raise InternalError("文件保存失败") from exc

    return StoredFile(
        relative_path=relative_path,
        abs_path=abs_path,
        mime_type=EXTENSION_TO_MIME[ext],
        size_bytes=len(content),
    )


def _compress_image(content: bytes, ext: str) -> tuple[bytes, str]:
    """Apply moderate compression to an uploaded image.

    Downscales so the longest edge is at most ``UPLOAD_MAX_EDGE_PX`` and
    re-encodes JPEG/WebP at a balanced quality; PNG stays lossless when possible.
    EXIF orientation is baked in so the stored pixels display upright. A
    re-encode failure rejects the upload rather than retaining metadata.
    """
    import io

    from PIL import ImageOps

    try:
        with Image.open(io.BytesIO(content)) as img:
            img = ImageOps.exif_transpose(img)

            longest = max(img.size)
            if longest > UPLOAD_MAX_EDGE_PX:
                scale = UPLOAD_MAX_EDGE_PX / longest
                new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
                img = img.resize(new_size, Image.LANCZOS)

            buffer = io.BytesIO()
            if ext in {"jpg", "jpeg"}:
                if img.mode not in {"RGB", "L"}:
                    img = img.convert("RGB")
                img.save(buffer, format="JPEG", quality=UPLOAD_JPEG_QUALITY, optimize=True, progressive=True)
            elif ext == "webp":
                img.save(buffer, format="WEBP", quality=UPLOAD_WEBP_QUALITY, method=6)
            elif ext == "png":
                img.save(buffer, format="PNG", optimize=True)
                if buffer.tell() > MAX_UPLOAD_BYTES:
                    buffer = io.BytesIO()
                    img.save(buffer, format="WEBP", quality=UPLOAD_WEBP_QUALITY, method=6)
                    ext = "webp"
            else:
                return content, ext
    except Exception as exc:  # noqa: BLE001
        raise InvalidParamError("图片无法安全解码与移除隐私元数据") from exc

    compressed = buffer.getvalue()
    # Always return the re-encoded pixels: keeping the original when it is
    # smaller would retain EXIF/GPS metadata that the privacy boundary promises
    # to strip.
    return (compressed, ext) if compressed else (content, ext)


def read_file_as_base64_data_url(relative_path: str) -> str:
    """Read a local static file and return a `data:image/...;base64,...` URL.

    Used to feed images to the model (never pass `/static/...` or any URL).
    """
    import base64

    abs_path = resolve_static_path(relative_path)
    ext = abs_path.rsplit(".", 1)[-1].lower() if "." in abs_path else "jpeg"
    mime = EXTENSION_TO_MIME.get(ext, "image/jpeg")
    try:
        with open(abs_path, "rb") as fp:
            encoded = base64.b64encode(fp.read()).decode("ascii")
    except OSError as exc:
        raise InternalError("读取本地图片失败") from exc
    return f"data:{mime};base64,{encoded}"


def calculate_file_sha256(relative_path: str) -> str:
    """Hash stored bytes without exposing image content to logs or callers."""
    abs_path = resolve_static_path(relative_path)
    digest = hashlib.sha256()
    try:
        with open(abs_path, "rb") as file:
            for chunk in iter(lambda: file.read(64 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise InvalidParamError("照片文件已不存在") from exc
    return digest.hexdigest()


def _allowed_download_host(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    entries = [value.strip().lower().rstrip(".") for value in settings.GENERATED_IMAGE_ALLOWED_HOSTS.split(",") if value.strip()]
    return any(host == entry or (entry.startswith(".") and host.endswith(entry) and host != entry[1:]) for entry in entries)


def _validate_public_download_url(source_url: str, resolver=socket.getaddrinfo) -> str:  # noqa: ANN001
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise InternalError("生成图下载地址不安全")
    if parsed.port not in {None, 443} or not _allowed_download_host(parsed.hostname):
        raise InternalError("生成图下载域名不在白名单")
    try:
        addresses = {item[4][0] for item in resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise InternalError("生成图下载域名无法解析") from exc
    if not addresses:
        raise InternalError("生成图下载域名无可用地址")
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if not address.is_global or any((address.is_private, address.is_loopback, address.is_link_local, address.is_reserved, address.is_multicast, address.is_unspecified)):
            raise InternalError("生成图下载地址指向非公网网络")
    return source_url


def _validate_downloaded_image(content: bytes, content_type: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_MIME_TYPES:
        raise InternalError("生成图响应类型不合法")
    try:
        with Image.open(io.BytesIO(content)) as image:
            detected = Image.MIME.get(image.format or "", "").lower()
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            if image.width < 320 or image.height < 320:
                raise ValueError("too small")
            if image.width * image.height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
    except Exception as exc:  # noqa: BLE001
        raise InternalError("生成图无法解码或尺寸不安全") from exc
    if detected != mime:
        raise InternalError("生成图文件特征与响应类型不一致")
    return mime


def download_to_static(source_url: str, relative_path: str, timeout: int | None = None) -> StoredFile:
    """Download a remote (temporary) URL and persist it at a static relative path.

    Used for model-generated images: the temporary public URL is downloaded and
    converted to a local relative path before it ever touches the DB. Raises
    `InternalError` (1003) on download/disk failure.
    """
    abs_path = resolve_static_path(relative_path)
    try:
        current_url = source_url
        with httpx.Client(timeout=timeout or settings.ARK_IMAGE_TIMEOUT_SECONDS, follow_redirects=False) as client:
            for redirect_count in range(4):
                _validate_public_download_url(current_url)
                with client.stream("GET", current_url) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        if redirect_count >= 3 or not resp.headers.get("location"):
                            raise InternalError("生成图下载重定向过多")
                        current_url = urljoin(current_url, resp.headers["location"])
                        continue
                    resp.raise_for_status()
                    declared = resp.headers.get("content-length")
                    if declared and int(declared) > settings.GENERATED_IMAGE_MAX_BYTES:
                        raise InternalError("生成图超过大小上限")
                    content_type = resp.headers.get("content-type", "")
                    parts: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes(64 * 1024):
                        total += len(chunk)
                        if total > settings.GENERATED_IMAGE_MAX_BYTES:
                            raise InternalError("生成图超过大小上限")
                        parts.append(chunk)
                    content = b"".join(parts)
                    mime_type = _validate_downloaded_image(content, content_type)
                    break
            else:
                raise InternalError("生成图下载失败")
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, InternalError):
            raise
        raise InternalError("下载生成图失败") from exc

    ext = relative_path.rsplit(".", 1)[-1].lower() if "." in relative_path else "jpg"
    if EXTENSION_TO_MIME.get(ext) != mime_type:
        raise InternalError("生成图扩展名与文件类型不一致")
    try:
        _ensure_parent_dir(abs_path)
        with open(abs_path, "wb") as fp:
            fp.write(content)
    except OSError as exc:
        raise InternalError("生成图落盘失败") from exc

    return StoredFile(
        relative_path=relative_path,
        abs_path=abs_path,
        mime_type=mime_type,
        size_bytes=len(content),
    )


def save_bytes_to_static(content: bytes, relative_path: str, mime_type: str | None = None) -> StoredFile:
    """Persist raw bytes to a static relative path."""
    abs_path = resolve_static_path(relative_path)
    ext = relative_path.rsplit(".", 1)[-1].lower() if "." in relative_path else "jpg"
    try:
        _ensure_parent_dir(abs_path)
        with open(abs_path, "wb") as fp:
            fp.write(content)
    except OSError as exc:
        raise InternalError("文件落盘失败") from exc
    return StoredFile(
        relative_path=relative_path,
        abs_path=abs_path,
        mime_type=mime_type or EXTENSION_TO_MIME.get(ext, "image/jpeg"),
        size_bytes=len(content),
    )


def delete_physical_file(relative_path: str) -> bool:
    """Delete the physical file for a relative path. Returns True if removed.

    Only `FileAssetService` may call this; business services must never call
    `os.remove` directly. Missing files must not crash callers.
    """
    try:
        abs_path = resolve_static_path(relative_path)
    except InvalidParamError:
        return False
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
            return True
    except OSError:
        return False
    return False
