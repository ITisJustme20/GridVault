"""Deterministic, privacy-conscious operator identity disc parameters."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from flask import Flask, current_app


DISC_CONTEXT = b"gridvault:operator-identity-disc:v1"
DISC_SECRET_FILENAME = ".identity-disc-secret"
DISC_ACCENTS = ("cyan", "teal", "lime")


def configure_identity_disc_secret(app: Flask, instance_path: Path) -> None:
    """Load a stable server-only secret without persisting identity data."""
    configured = app.config.get("IDENTITY_DISC_SECRET")
    if configured:
        configured_value = str(configured)
        if len(configured_value) < 32:
            raise RuntimeError(
                "The Identity Disc secret must contain at least 32 characters."
            )
        app.config["IDENTITY_DISC_SECRET"] = configured_value
        return

    if app.config.get("TESTING"):
        app.config["IDENTITY_DISC_SECRET"] = (
            f"gridvault-test-only:{app.config['SECRET_KEY']}"
        )
        return

    secret_path = instance_path / DISC_SECRET_FILENAME
    try:
        secret_value = secret_path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        secret_value = secrets.token_hex(32)
        try:
            descriptor = os.open(
                secret_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            secret_value = secret_path.read_text(encoding="ascii").strip()
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as secret_file:
                secret_file.write(secret_value)
            app.logger.warning(
                "Generated a development Identity Disc secret in the ignored "
                "instance directory. Configure IDENTITY_DISC_SECRET for deployment."
            )
    if len(secret_value) < 32:
        raise RuntimeError("The Identity Disc secret must contain at least 32 characters.")
    app.config["IDENTITY_DISC_SECRET"] = secret_value


def _fingerprint(user_id: int) -> bytes:
    if not isinstance(user_id, int) or user_id < 1:
        raise ValueError("An immutable persisted operator ID is required.")
    secret_value = current_app.config.get("IDENTITY_DISC_SECRET")
    if not isinstance(secret_value, str) or len(secret_value) < 32:
        raise RuntimeError("Identity Disc secret is unavailable.")
    message = DISC_CONTEXT + b":" + str(user_id).encode("ascii")
    return hmac.new(
        secret_value.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()


def _dash_pair(first: int, second: int, *, base: int) -> list[int]:
    return [base + first % 10, 5 + second % 8]


def identity_disc_for_user(user) -> dict[str, object]:
    """Return a code and constrained public SVG parameters for one operator."""
    digest = _fingerprint(user.id)
    code_hex = digest[:6].hex().upper()
    return {
        "code": "-".join(code_hex[index : index + 4] for index in range(0, 12, 4)),
        "visual": {
            "version": 1,
            "accent": DISC_ACCENTS[digest[6] % len(DISC_ACCENTS)],
            "outer_rotation": digest[7] % 90,
            "outer_dash": _dash_pair(digest[8], digest[9], base=14),
            "middle_rotation": digest[10] % 120,
            "middle_dash": _dash_pair(digest[11], digest[12], base=10),
            "inner_rotation": digest[13] % 180,
            "inner_dash": _dash_pair(digest[14], digest[15], base=7),
            "core_rotation": digest[16] % 60,
            "circuit_rotation": digest[17] % 90,
            "spokes": sorted(
                {
                    (digest[18 + index] % 12) * 30
                    for index in range(6)
                }
            ),
        },
    }
