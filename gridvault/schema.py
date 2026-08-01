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


def _add_missing_user_columns() -> None:
    """Add access-control flags while preserving legacy operator behavior."""
    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("user")}
    with db.engine.begin() as connection:
        if "is_admin" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE user ADD COLUMN is_admin "
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "has_seen_orientation" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE user ADD COLUMN has_seen_orientation "
                    "BOOLEAN NOT NULL DEFAULT 1"
                )
            )


def _add_missing_message_columns() -> None:
    """Add the nullable conversation link without rewriting legacy messages."""
    inspector = inspect(db.engine)
    if "message" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("message")}
    with db.engine.begin() as connection:
        if "conversation_id" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE message ADD COLUMN conversation_id "
                    "INTEGER REFERENCES conversation(id)"
                )
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_message_conversation_id "
                "ON message (conversation_id)"
            )
        )


def _associate_grid_history() -> None:
    """Create the single Grid conversation and attach every legacy message."""
    from .chat_service import ensure_grid_membership, get_grid_conversation
    from .models import Message, User

    grid = get_grid_conversation()
    db.session.execute(
        db.update(Message)
        .where(Message.conversation_id.is_(None))
        .values(conversation_id=grid.id)
    )
    users = db.session.execute(db.select(User)).scalars().all()
    for user in users:
        ensure_grid_membership(user)
    db.session.commit()


def ensure_schema(app) -> None:
    """Create missing schema objects without altering existing data."""

    with app.app_context():
        db.create_all()
        _add_missing_user_columns()
        _add_missing_message_columns()
        _add_missing_design_columns()
        _associate_grid_history()
