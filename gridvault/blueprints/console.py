"""Mission Console dashboard routes."""

from flask import Blueprint, render_template
from flask_login import login_required

from ..extensions import db
from ..models import Message, Project, ProjectActivity, User


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
    recent_messages = db.session.execute(
        db.select(Message).order_by(Message.created_at.desc()).limit(3)
    ).scalars().all()
    recent_project_activity = db.session.execute(
        db.select(ProjectActivity)
        .order_by(ProjectActivity.created_at.desc())
        .limit(4)
    ).scalars().all()

    return render_template(
        "console/dashboard.html",
        operator_count=operator_count,
        message_count=message_count,
        active_project_count=active_project_count,
        recent_messages=recent_messages,
        recent_project_activity=recent_project_activity,
    )
