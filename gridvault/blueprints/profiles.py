"""Compact operator profiles and private trust controls."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..chat_service import display_name
from ..extensions import db
from ..identity_disc import identity_disc_for_user
from ..models import PROFILE_SPECIALTIES, REPORT_CATEGORIES, UserBlock, UserReport
from ..realtime import broadcast_online_users
from ..trust_service import (
    block_by,
    find_user_by_callsign,
    shared_group_conversations,
    validate_profile,
    validate_report,
)


profiles_bp = Blueprint("profiles", __name__)


def _operator_or_404(callsign: str):
    operator = find_user_by_callsign(callsign)
    if operator is None:
        abort(404)
    return operator


@profiles_bp.get("/profile")
@login_required
def my_profile():
    return redirect(
        url_for("profiles.view_profile", callsign=current_user.username)
    )


@profiles_bp.get("/operators/<callsign>")
@login_required
def view_profile(callsign: str):
    operator = _operator_or_404(callsign)
    shared_groups = shared_group_conversations(current_user.id, operator.id)
    blocked_by_viewer = (
        block_by(current_user.id, operator.id)
        if operator.id != current_user.id
        else None
    )
    return render_template(
        "profiles/view.html",
        operator=operator,
        shared_groups=shared_groups,
        display_name=display_name,
        blocked_by_viewer=blocked_by_viewer,
        identity_disc=identity_disc_for_user(operator),
    )


@profiles_bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        specialty, status_text, errors = validate_profile(
            request.form.get("specialty", ""),
            request.form.get("status_text", ""),
        )
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "profiles/edit.html",
                specialties=PROFILE_SPECIALTIES,
                selected_specialty=specialty,
                status_text=status_text,
            ), 400
        current_user.specialty = specialty
        current_user.status_text = status_text or None
        db.session.commit()
        flash("Operator profile updated.", "success")
        return redirect(
            url_for("profiles.view_profile", callsign=current_user.username)
        )
    return render_template(
        "profiles/edit.html",
        specialties=PROFILE_SPECIALTIES,
        selected_specialty=current_user.specialty or "",
        status_text=current_user.status_text or "",
    )


@profiles_bp.post("/operators/<callsign>/block")
@login_required
def block_operator(callsign: str):
    operator = _operator_or_404(callsign)
    if operator.id == current_user.id:
        abort(400)
    if block_by(current_user.id, operator.id) is None:
        db.session.add(UserBlock(blocker_id=current_user.id, blocked_id=operator.id))
        db.session.commit()
        broadcast_online_users()
    flash("Operator blocked. Direct contact is disabled.", "success")
    return redirect(url_for("profiles.view_profile", callsign=operator.username))


@profiles_bp.post("/operators/<callsign>/unblock")
@login_required
def unblock_operator(callsign: str):
    operator = _operator_or_404(callsign)
    existing = block_by(current_user.id, operator.id)
    if existing is not None:
        db.session.delete(existing)
        db.session.commit()
        broadcast_online_users()
    flash("Operator unblocked. Direct contact is available.", "success")
    return redirect(url_for("profiles.view_profile", callsign=operator.username))


@profiles_bp.route("/operators/<callsign>/report", methods=["GET", "POST"])
@login_required
def report_operator(callsign: str):
    operator = _operator_or_404(callsign)
    if operator.id == current_user.id:
        abort(400)
    if request.method == "POST":
        category, explanation, errors = validate_report(
            request.form.get("category", ""),
            request.form.get("explanation", ""),
        )
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "profiles/report.html",
                operator=operator,
                categories=REPORT_CATEGORIES,
                selected_category=category,
                explanation=explanation,
            ), 400
        report = UserReport(
            reporter_id=current_user.id,
            reported_user_id=operator.id,
            category=category,
            explanation=explanation,
        )
        db.session.add(report)
        db.session.commit()
        from ..signal_service import administrator_user_ids, broadcast_signal_updates

        broadcast_signal_updates(administrator_user_ids())
        flash("Report submitted to GridVault administrators.", "success")
        return redirect(url_for("profiles.view_profile", callsign=operator.username))
    return render_template(
        "profiles/report.html",
        operator=operator,
        categories=REPORT_CATEGORIES,
        selected_category="",
        explanation="",
    )
