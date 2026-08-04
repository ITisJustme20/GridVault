"""Defensive validation and private storage helpers for chat attachments."""

from __future__ import annotations

import io
import json
import re
import struct
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from flask import current_app, url_for
from werkzeug.utils import secure_filename

from .models import ChatAttachment


TEXT_PREVIEW_MAX_BYTES = 256 * 1024
DANGEROUS_EXTENSIONS = {
    "apk", "bat", "cmd", "com", "dll", "dmg", "exe", "iso", "jar",
    "msi", "ps1", "scr", "sh",
}
DANGEROUS_MIME_TYPES = {
    "application/x-dosexec",
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-sh",
    "application/x-sharedlib",
}


@dataclass(frozen=True)
class FileRule:
    category: str
    mime_type: str
    validator: str
    accepted_mime_types: tuple[str, ...] = ()


def _rule(category, mime_type, validator, *accepted):
    return FileRule(category, mime_type, validator, tuple(accepted))


FILE_RULES = {
    "png": _rule("image", "image/png", "png", "image/png"),
    "jpg": _rule("image", "image/jpeg", "jpeg", "image/jpeg", "image/pjpeg"),
    "jpeg": _rule("image", "image/jpeg", "jpeg", "image/jpeg", "image/pjpeg"),
    "webp": _rule("image", "image/webp", "webp", "image/webp"),
    "gif": _rule("image", "image/gif", "gif", "image/gif"),
    "pdf": _rule("document", "application/pdf", "pdf", "application/pdf"),
    "txt": _rule("document", "text/plain", "text", "text/plain"),
    "csv": _rule("document", "text/csv", "text", "text/csv", "application/csv"),
    "json": _rule("document", "application/json", "json", "application/json", "text/json"),
    "md": _rule("document", "text/markdown", "text", "text/markdown", "text/plain"),
    "docx": _rule("document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"),
    "xlsx": _rule("document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"),
    "pptx": _rule("document", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/zip"),
    "py": _rule("code", "text/x-python", "text", "text/x-python", "text/plain"),
    "js": _rule("code", "text/javascript", "text", "text/javascript", "application/javascript", "application/x-javascript", "text/plain"),
    "ts": _rule("code", "text/typescript", "text", "text/typescript", "application/typescript", "text/plain"),
    "html": _rule("code", "text/html", "text", "text/html", "text/plain"),
    "css": _rule("code", "text/css", "text", "text/css", "text/plain"),
    "sql": _rule("code", "application/sql", "text", "application/sql", "text/plain"),
    "java": _rule("code", "text/x-java-source", "text", "text/x-java-source", "text/plain"),
    "c": _rule("code", "text/x-c", "text", "text/x-c", "text/plain"),
    "cpp": _rule("code", "text/x-c++", "text", "text/x-c++", "text/plain"),
    "h": _rule("code", "text/x-c", "text", "text/x-c", "text/plain"),
    "cs": _rule("code", "text/x-csharp", "text", "text/plain"),
    "rs": _rule("code", "text/x-rust", "text", "text/plain"),
    "go": _rule("code", "text/x-go", "text", "text/plain"),
    "xml": _rule("code", "application/xml", "text", "application/xml", "text/xml", "text/plain"),
    "yaml": _rule("code", "application/yaml", "text", "application/yaml", "text/yaml", "text/plain"),
    "yml": _rule("code", "application/yaml", "text", "application/yaml", "text/yaml", "text/plain"),
    "toml": _rule("code", "application/toml", "text", "application/toml", "text/plain"),
    "ini": _rule("code", "text/plain", "text", "text/plain"),
    "stl": _rule("design", "model/stl", "stl", "model/stl", "application/sla"),
    "obj": _rule("design", "model/obj", "obj", "model/obj", "text/plain"),
    "step": _rule("design", "model/step", "step", "model/step"),
    "stp": _rule("design", "model/step", "step", "model/step"),
    "dxf": _rule("design", "image/vnd.dxf", "dxf", "image/vnd.dxf", "application/dxf", "text/plain"),
    "svg": _rule("design", "image/svg+xml", "svg", "image/svg+xml", "text/xml"),
    "zip": _rule("archive", "application/zip", "zip", "application/zip", "application/x-zip-compressed"),
}


class FileValidationError(ValueError):
    """A safe, user-facing upload validation failure."""


def allowed_extensions() -> tuple[str, ...]:
    return tuple(sorted(FILE_RULES))


def sanitize_display_filename(raw_filename: str) -> tuple[str, str]:
    if not raw_filename or "\x00" in raw_filename:
        raise FileValidationError("Choose a file with a valid filename.")
    basename = raw_filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not basename or basename in {".", ".."}:
        raise FileValidationError("Choose a file with a valid filename.")
    suffixes = [part.lower() for part in basename.split(".")[1:] if part]
    if not suffixes:
        raise FileValidationError("This file type is not supported.")
    if any(suffix in DANGEROUS_EXTENSIONS for suffix in suffixes):
        raise FileValidationError("Executable and dangerous file types are blocked.")
    if "js" in suffixes[:-1]:
        raise FileValidationError("Disguised JavaScript files are blocked.")
    extension = suffixes[-1]
    if extension not in FILE_RULES:
        raise FileValidationError("This file type is not supported.")
    sanitized = secure_filename(basename)
    if not sanitized:
        raise FileValidationError("Choose a file with a valid filename.")
    sanitized = sanitized[:255]
    if sanitized.rsplit(".", 1)[-1].lower() != extension:
        sanitized = f"{sanitized.rsplit('.', 1)[0][:240]}.{extension}"
    return sanitized, extension


def _decode_text(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _valid_zip(data: bytes, expected_root: str | None = None) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 10_000 or sum(item.file_size for item in entries) > 512 * 1024 * 1024:
                return False
            names = [item.filename for item in entries]
            return expected_root is None or any(
                name.startswith(expected_root) for name in names
            )
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False


def _validate_signature(data: bytes, extension: str, validator: str) -> bool:
    if validator == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if validator == "jpeg":
        return data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if validator == "gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if validator == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if validator == "pdf":
        return data.startswith(b"%PDF-")
    if validator == "zip":
        return _valid_zip(data)
    if validator in {"docx", "xlsx", "pptx"}:
        root = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}[validator]
        return _valid_zip(data, root)
    text = _decode_text(data)
    if validator == "text":
        if text is None:
            return False
        if extension == "json":
            try:
                json.loads(text)
            except json.JSONDecodeError:
                return False
        return True
    if validator == "json":
        if text is None:
            return False
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False
    if validator == "svg":
        return text is not None and re.search(r"<\s*svg(?:\s|>)", text, re.I) is not None
    if validator == "step":
        return text is not None and "ISO-10303-21" in text[:200].upper()
    if validator == "obj":
        return text is not None and re.search(r"(?m)^\s*(?:v|vt|vn|f|o|g)\s+", text) is not None
    if validator == "dxf":
        return data.startswith(b"AutoCAD Binary DXF") or (
            text is not None and "SECTION" in text[:1000].upper()
        )
    if validator == "stl":
        if text is not None and text.lstrip().lower().startswith("solid"):
            return True
        if len(data) < 84:
            return False
        triangle_count = struct.unpack("<I", data[80:84])[0]
        return len(data) == 84 + triangle_count * 50
    return False


def validate_upload(uploaded, maximum: int) -> tuple[bytes, str, str, FileRule]:
    filename, extension = sanitize_display_filename(uploaded.filename or "")
    data = uploaded.stream.read(maximum + 1)
    if not data:
        raise FileValidationError("The selected file is empty.")
    if len(data) > maximum:
        raise FileValidationError(
            f"The file is larger than the {human_file_size(maximum)} limit."
        )
    rule = FILE_RULES[extension]
    claimed_mime = (uploaded.mimetype or "application/octet-stream").split(";", 1)[0].lower()
    if claimed_mime in DANGEROUS_MIME_TYPES:
        raise FileValidationError("The file content type is not permitted.")
    accepted = set(rule.accepted_mime_types) | {"application/octet-stream"}
    if claimed_mime not in accepted:
        raise FileValidationError("The filename and reported file type do not match.")
    if not _validate_signature(data, extension, rule.validator):
        raise FileValidationError("The file content does not match its permitted type.")
    return data, filename, extension, rule


def _storage_root() -> Path:
    root = Path(current_app.config["CHAT_UPLOAD_FOLDER"]).resolve()
    static_root = Path(current_app.static_folder).resolve()
    if root == static_root or static_root in root.parents:
        raise RuntimeError("CHAT_UPLOAD_FOLDER must be outside the public static directory.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def store_private_file(data: bytes, extension: str) -> str:
    root = _storage_root()
    for _ in range(5):
        storage_key = f"{uuid.uuid4().hex}.{extension}"
        target = (root / storage_key).resolve()
        if target.parent != root:
            raise RuntimeError("Invalid private upload destination.")
        try:
            with target.open("xb") as handle:
                handle.write(data)
            return storage_key
        except FileExistsError:
            continue
    raise RuntimeError("Could not allocate private attachment storage.")


def discard_private_file(storage_key: str) -> None:
    """Remove a just-written file when its database transaction fails."""
    root = _storage_root()
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]+", storage_key):
        return
    target = (root / storage_key).resolve()
    if target.parent == root:
        target.unlink(missing_ok=True)


def attachment_path(attachment: ChatAttachment) -> Path:
    root = _storage_root()
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]+", attachment.storage_key):
        raise FileNotFoundError
    path = (root / attachment.storage_key).resolve()
    if path.parent != root or not path.is_file():
        raise FileNotFoundError
    return path


def attachment_can_preview(attachment: ChatAttachment) -> bool:
    extension = attachment.storage_key.rsplit(".", 1)[-1]
    if attachment.category == "image":
        return extension in {"png", "jpg", "jpeg", "webp", "gif"}
    return (
        attachment.category in {"document", "code"}
        and extension not in {"pdf", "docx", "xlsx", "pptx"}
        and attachment.byte_size <= TEXT_PREVIEW_MAX_BYTES
    )


def serialize_attachment(attachment: ChatAttachment) -> dict[str, object]:
    previewable = attachment_can_preview(attachment)
    return {
        "id": attachment.id,
        "filename": attachment.original_filename,
        "byte_size": attachment.byte_size,
        "size": human_file_size(attachment.byte_size),
        "mime_type": attachment.detected_mime_type,
        "category": attachment.category.title(),
        "uploader": attachment.uploader.username,
        "uploaded_at": attachment.uploaded_at.isoformat(),
        "preview_url": url_for("hub.preview_attachment", attachment_id=attachment.id) if previewable else None,
        "thumbnail_url": url_for(
            "hub.preview_attachment",
            attachment_id=attachment.id,
            inline=1,
        ) if attachment.category == "image" else None,
        "download_url": url_for("hub.download_attachment", attachment_id=attachment.id),
        "metadata_url": url_for("hub.attachment_metadata", attachment_id=attachment.id),
    }


def human_file_size(byte_size: int) -> str:
    if byte_size < 1024:
        return f"{byte_size} B"
    if byte_size < 1024 * 1024:
        return f"{byte_size / 1024:.1f} KB"
    return f"{byte_size / (1024 * 1024):.1f} MB"
