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

DESIGN_STAGES = (
    "Concept",
    "Exploring",
    "In Review",
    "Approved",
    "Rejected",
    "Archived",
)

CONVERSATION_TYPES = ("grid", "direct", "group")


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


class Conversation(db.Model):
    __table_args__ = (
        db.CheckConstraint(
            "type IN ('grid', 'direct', 'group')",
            name="ck_conversation_type",
        ),
        db.Index("idx_conversation_type_updated", "type", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10), nullable=False, index=True)
    name = db.Column(db.String(80))
    direct_key = db.Column(db.String(40), unique=True, index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
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
        backref=db.backref("created_conversations", lazy=True),
    )
    memberships = db.relationship(
        "ConversationMember",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMember.joined_at",
    )
    messages = db.relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Message.conversation_id",
        order_by="Message.created_at",
    )


class ConversationMember(db.Model):
    __table_args__ = (
        db.Index("idx_conversation_member_user", "user_id", "conversation_id"),
    )

    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    joined_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_read_message_id = db.Column(
        db.Integer,
        db.ForeignKey("message.id", ondelete="SET NULL"),
    )

    conversation = db.relationship("Conversation", back_populates="memberships")
    user = db.relationship(
        "User",
        backref=db.backref("conversation_memberships", lazy=True),
    )
    last_read_message = db.relationship(
        "Message",
        foreign_keys=[last_read_message_id],
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
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("conversation.id"),
        nullable=True,
        index=True,
    )

    conversation = db.relationship(
        "Conversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
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


design_collaborator = db.Table(
    "design_collaborator",
    db.Column(
        "design_id",
        db.Integer,
        db.ForeignKey("design.id", ondelete="CASCADE"),
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


class Design(db.Model):
    __table_args__ = (
        db.CheckConstraint(
            "stage IN ('Concept', 'Exploring', 'In Review', 'Approved', "
            "'Rejected', 'Archived')",
            name="ck_design_stage",
        ),
        db.Index("idx_design_stage_updated", "stage", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    codename = db.Column(
        db.String(40, collation="NOCASE"),
        unique=True,
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(120), nullable=False)
    problem = db.Column(db.Text, nullable=False)
    proposed_solution = db.Column(db.Text, nullable=False)
    intended_user = db.Column(db.String(300), nullable=False)
    design_goals = db.Column(db.Text, nullable=False)
    constraints = db.Column(db.Text, nullable=False, default="")
    materials = db.Column(db.Text, nullable=False, default="")
    dimensions = db.Column(db.String(500), nullable=False, default="")
    components = db.Column(db.Text, nullable=False, default="")
    risks = db.Column(db.Text, nullable=False, default="")
    references = db.Column(db.Text, nullable=False, default="")
    stage = db.Column(db.String(20), nullable=False, default="Concept")
    revision_number = db.Column(db.Integer, nullable=False, default=1)
    published_revision_number = db.Column(db.Integer)
    board_state = db.Column(db.Text, nullable=False, default="[]")
    board_version = db.Column(db.Integer, nullable=False, default=0)
    cover_filename = db.Column(db.String(255))
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id"),
        index=True,
    )
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

    project = db.relationship(
        "Project",
        backref=db.backref("designs", lazy=True),
    )
    creator = db.relationship(
        "User",
        foreign_keys=[creator_id],
        backref=db.backref("created_designs", lazy=True),
    )
    collaborators = db.relationship(
        "User",
        secondary=design_collaborator,
        backref=db.backref("collaborative_designs", lazy=True),
        order_by="User.username",
    )
    revisions = db.relationship(
        "DesignRevision",
        back_populates="design",
        cascade="all, delete-orphan",
    )
    comments = db.relationship(
        "DesignReviewComment",
        back_populates="design",
        cascade="all, delete-orphan",
    )
    status_history = db.relationship(
        "DesignStatusHistory",
        back_populates="design",
        cascade="all, delete-orphan",
    )
    activities = db.relationship(
        "DesignActivity",
        back_populates="design",
        cascade="all, delete-orphan",
    )
    assets = db.relationship(
        "DesignAsset",
        back_populates="design",
        cascade="all, delete-orphan",
    )


class DesignRevision(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "design_id",
            "revision_number",
            name="uq_design_revision_number",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(
        db.Integer,
        db.ForeignKey("design.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = db.Column(db.Integer, nullable=False)
    snapshot = db.Column(db.Text, nullable=False)
    change_note = db.Column(db.String(500), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    design = db.relationship("Design", back_populates="revisions")
    author = db.relationship("User")


class DesignReviewComment(db.Model):
    __table_args__ = (
        db.Index(
            "idx_design_review_comment_created",
            "design_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(
        db.Integer,
        db.ForeignKey("design.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    design = db.relationship("Design", back_populates="comments")
    author = db.relationship("User")


class DesignStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(
        db.Integer,
        db.ForeignKey("design.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    from_stage = db.Column(db.String(20))
    to_stage = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(500), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    design = db.relationship("Design", back_populates="status_history")
    actor = db.relationship("User")


class DesignActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(
        db.Integer,
        db.ForeignKey("design.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(500), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    design = db.relationship("Design", back_populates="activities")
    actor = db.relationship("User")


class DesignAsset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    design_id = db.Column(
        db.Integer,
        db.ForeignKey("design.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploader_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), unique=True, nullable=False)
    mime_type = db.Column(db.String(40), nullable=False)
    byte_size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    design = db.relationship("Design", back_populates="assets")
    uploader = db.relationship("User")
