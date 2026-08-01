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

    @classmethod
    def validate(cls) -> None:
        if cls.ENVIRONMENT == "production" and not cls.SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY must be set when GRIDVAULT_ENV=production."
            )
