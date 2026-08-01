"""Additive database schema management.

GridVault never drops or rewrites existing tables at application startup.
SQLAlchemy's check-first table creation adds missing tables and indexes. Small,
explicit ALTER statements add new nullable/defaulted columns without rewriting
or deleting legacy User, Message, Project, or Design rows.
"""

from sqlalchemy import inspect, text

from .extensions import db


def _add_missing_design_columns() -> None:
    """Apply additive-only columns needed by newer Design Lab releases."""
    inspector = inspect(db.engine)
    if "design" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("design")}
    if "board_version" not in columns:
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE design ADD COLUMN board_version "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            )


def ensure_schema(app) -> None:
    """Create missing schema objects without altering existing data."""

    with app.app_context():
        db.create_all()
        _add_missing_design_columns()
