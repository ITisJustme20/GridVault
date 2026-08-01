"""The Hub's HTTP routes."""

from flask import Blueprint, render_template
from flask_login import login_required

from ..extensions import db
from ..models import Message


hub_bp = Blueprint("hub", __name__)


@hub_bp.get("/hub")
@hub_bp.get("/chat")
@login_required
def chat():
    saved_messages = db.session.execute(
        db.select(Message).order_by(Message.created_at.desc()).limit(100)
    ).scalars().all()
    saved_messages.reverse()
    return render_template("hub/chat.html", messages=saved_messages)
