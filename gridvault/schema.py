"""Additive database schema management.

GridVault never drops or rewrites existing tables at application startup.
SQLAlchemy's check-first table creation adds only missing tables and indexes,
which keeps legacy User and Message rows intact while enabling new modules.
"""

from .extensions import db


def ensure_schema(app) -> None:
    """Create missing schema objects without altering existing data."""

    with app.app_context():
        db.create_all()
