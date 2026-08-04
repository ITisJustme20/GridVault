"""Authenticated Live Grid navigation, broad presence, and privacy settings."""

from flask import Blueprint, flash, redirect, render_template, url_for, request
from flask_login import current_user, login_required

from ..chat_service import accessible_conversations
from ..extensions import db
from ..models import PRESENCE_VISIBILITIES
from ..realtime import broadcast_live_grid_presence


live_grid_bp = Blueprint("live_grid", __name__)


@live_grid_bp.get("/live-grid")
@login_required
def index():
    conversations = accessible_conversations(current_user)
    file_conversation = next(
        (
            conversation
            for conversation in conversations
            if conversation.type in {"direct", "group"}
        ),
        None,
    )
    file_vault_url = (
        url_for("hub.chat", conversation=file_conversation.id, files=1)
        if file_conversation is not None
        else url_for("hub.chat")
    )
    sectors = (
        ("GRID", url_for("hub.chat"), "Shared Grid conversation"),
        ("DIRECT", url_for("hub.chat", area="direct"), "Private one-to-one conversations"),
        ("GROUPS", url_for("hub.chat", area="groups"), "Private group conversations"),
        ("VC BOARD", url_for("design_lab.index"), "Visual planning and design dossiers"),
        ("FILE VAULT", file_vault_url, "Authorized conversation files"),
        (
            "ACCESS",
            url_for("profiles.view_profile", callsign=current_user.username),
            "Operator profile and identity controls",
        ),
    )
    return render_template(
        "live_grid/index.html",
        sectors=sectors,
        presence_visibilities=PRESENCE_VISIBILITIES,
        presence_sector="ACTIVE",
    )


@live_grid_bp.post("/live-grid/presence-visibility")
@login_required
def update_presence_visibility():
    visibility = request.form.get("presence_visibility", "").strip()
    if visibility not in PRESENCE_VISIBILITIES:
        flash("Select Sector or Active presence visibility.", "error")
        return redirect(url_for("live_grid.index")), 400
    current_user.presence_visibility = visibility
    db.session.commit()
    broadcast_live_grid_presence()
    flash("Presence visibility updated.", "success")
    return redirect(url_for("live_grid.index"))
