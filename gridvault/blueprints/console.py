"""Mission Console dashboard routes."""

from flask import Blueprint, render_template
from flask_login import login_required

from ..extensions import db
from ..models import (
    Conversation,
    Design,
    DesignActivity,
    Message,
    Project,
    ProjectActivity,
    User,
)


console_bp = Blueprint("console", __name__)


@console_bp.get("/")
@console_bp.get("/mission-console")
@login_required
def dashboard():
    operator_count = db.session.scalar(db.select(db.func.count(User.id))) or 0
    message_count = db.session.scalar(db.select(db.func.count(Message.id))) or 0
    active_project_count = db.session.scalar(
        db.select(db.func.count(Project.id)).where(Project.status == "Active")
    ) or 0
    total_design_count = db.session.scalar(
        db.select(db.func.count(Design.id))
    ) or 0
    design_review_count = db.session.scalar(
        db.select(db.func.count(Design.id)).where(Design.stage == "In Review")
    ) or 0
    approved_design_count = db.session.scalar(
        db.select(db.func.count(Design.id)).where(Design.stage == "Approved")
    ) or 0
    recent_messages = db.session.execute(
        db.select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.type == "grid")
        .order_by(Message.created_at.desc())
        .limit(3)
    ).scalars().all()
    recent_project_activity = db.session.execute(
        db.select(ProjectActivity)
        .order_by(ProjectActivity.created_at.desc())
        .limit(4)
    ).scalars().all()
    recent_design_activity = db.session.execute(
        db.select(DesignActivity)
        .order_by(DesignActivity.created_at.desc(), DesignActivity.id.desc())
        .limit(4)
    ).scalars().all()

    return render_template(
        "console/dashboard.html",
        operator_count=operator_count,
        message_count=message_count,
        active_project_count=active_project_count,
        total_design_count=total_design_count,
        design_review_count=design_review_count,
        approved_design_count=approved_design_count,
        recent_messages=recent_messages,
        recent_project_activity=recent_project_activity,
        recent_design_activity=recent_design_activity,
    )
