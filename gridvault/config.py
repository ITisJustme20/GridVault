"""Runtime configuration for GridVault."""

from __future__ import annotations

import os
from datetime import timedelta


class Config:
    """Safe defaults shared by every GridVault environment."""

    ENVIRONMENT = os.environ.get("GRIDVAULT_ENV", "development").lower()
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///gridvault.db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    SOCKETIO_CORS_ALLOWED_ORIGINS = os.environ.get(
        "SOCKETIO_CORS_ALLOWED_ORIGINS",
    )
    DESIGN_UPLOAD_FOLDER = os.environ.get("DESIGN_UPLOAD_FOLDER")
    DESIGN_UPLOAD_MAX_BYTES = int(
        os.environ.get("DESIGN_UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
    )
    CHAT_UPLOAD_FOLDER = os.environ.get("CHAT_UPLOAD_FOLDER")
    CHAT_UPLOAD_MAX_BYTES = int(
        os.environ.get("CHAT_UPLOAD_MAX_BYTES", 25 * 1024 * 1024)
    )
    MAX_CONTENT_LENGTH = max(
        DESIGN_UPLOAD_MAX_BYTES,
        CHAT_UPLOAD_MAX_BYTES,
    ) + 1024 * 1024

    @classmethod
    def validate(cls) -> None:
        if cls.ENVIRONMENT == "production" and not cls.SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY must be set when GRIDVAULT_ENV=production."
            )
        if not 1024 <= cls.DESIGN_UPLOAD_MAX_BYTES <= 10 * 1024 * 1024:
            raise RuntimeError(
                "DESIGN_UPLOAD_MAX_BYTES must be between 1 KB and 10 MB."
            )
        if not 1024 <= cls.CHAT_UPLOAD_MAX_BYTES <= 100 * 1024 * 1024:
            raise RuntimeError(
                "CHAT_UPLOAD_MAX_BYTES must be between 1 KB and 100 MB."
            )
