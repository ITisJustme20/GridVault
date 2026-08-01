"""Persistent GridVault data models.

The table and column names intentionally match the original single-file app so
existing SQLite databases continue to work without a migration.
"""

from datetime import datetime, timezone

from flask_login import UserMixin

from .extensions import db


PROJECT_STATUSES = (
    "Concept",
    "Research",
    "Active",
    "Prototype",
    "Testing",
    "Paused",
    "Complete",
    "Archived",
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(
        db.String(30),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    messages = db.relationship(
        "Message",
        backref="author",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
    )


project_assignment = db.Table(
    "project_assignment",
    db.Column(
        "project_id",
        db.Integer,
        db.ForeignKey("project.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "user_id",
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "assigned_at",
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    ),
)


class Project(db.Model):
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('Concept', 'Research', 'Active', 'Prototype', "
            "'Testing', 'Paused', 'Complete', 'Archived')",
            name="ck_project_status",
        ),
        db.Index("idx_project_status_updated", "status", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    codename = db.Column(
        db.String(40, collation="NOCASE"),
        unique=True,
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Concept")
    creator_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )

    creator = db.relationship(
        "User",
        foreign_keys=[creator_id],
        backref=db.backref("created_projects", lazy=True),
    )
    assigned_operators = db.relationship(
        "User",
        secondary=project_assignment,
        backref=db.backref("assigned_projects", lazy=True),
        order_by="User.username",
    )
    objectives = db.relationship(
        "ProjectObjective",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectObjective.position",
    )
    activities = db.relationship(
        "ProjectActivity",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    comments = db.relationship(
        "ProjectComment",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectObjective(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body = db.Column(db.String(300), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    is_complete = db.Column(db.Boolean, nullable=False, default=False)

    project = db.relationship("Project", back_populates="objectives")


class ProjectActivity(db.Model):
    __table_args__ = (
        db.Index(
            "idx_project_activity_project_created",
            "project_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(500), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    project = db.relationship("Project", back_populates="activities")
    actor = db.relationship("User")


class ProjectComment(db.Model):
    __table_args__ = (
        db.Index(
            "idx_project_comment_project_created",
            "project_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    body = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    project = db.relationship("Project", back_populates="comments")
    author = db.relationship("User")
