"""Administrator-only invitation management."""

from datetime import timedelta
import re

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..invitations import invitation_label, is_gridvault_admin, issue_invitation, refresh_expired_invitations, utc_now
from ..models import Invitation, User, UserReport
from ..trust_service import HTML_PATTERN, find_user_by_callsign


access_control_bp = Blueprint("access_control", __name__)
PUBLIC_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
EXPIRATION_OPTIONS = {
    "none": None,
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _require_admin() -> None:
    if not is_gridvault_admin(current_user):
        abort(403)


def _render_access_control(*, new_invite_code: str | None = None):
    refresh_expired_invitations()
    invitations = db.session.execute(
        db.select(Invitation).order_by(Invitation.created_at.desc())
    ).scalars().all()
    operators = db.session.execute(
        db.select(User).order_by(db.func.lower(User.username))
    ).scalars().all()
    reports = db.session.execute(
        db.select(UserReport).order_by(UserReport.created_at.desc())
    ).scalars().all()
    report_counts = {
        operator.id: sum(
            1 for report in reports if report.reported_user_id == operator.id
        )
        for operator in operators
    }
    grouped = {
        status: [invite for invite in invitations if invite.status == status]
        for status in ("Active", "Used", "Expired", "Revoked")
    }
    return render_template(
        "access_control/index.html",
        grouped_invitations=grouped,
        operators=operators,
        reports=reports,
        report_counts=report_counts,
        new_invite_code=new_invite_code,
        invitation_label=invitation_label,
    )


@access_control_bp.get("/access-control")
@login_required
def index():
    _require_admin()
    return _render_access_control()


@access_control_bp.post("/access-control/invitations")
@login_required
def create_invitation():
    _require_admin()
    expiration_key = request.form.get("expiration", "none")
    if expiration_key not in EXPIRATION_OPTIONS:
        flash("Select a valid expiration period.", "error")
        return _render_access_control(), 400
    try:
        _, plaintext_code = issue_invitation(
            current_user,
            reserved_callsign=request.form.get("reserved_callsign", ""),
            expires_in=EXPIRATION_OPTIONS[expiration_key],
        )
    except ValueError as error:
        flash(str(error), "error")
        return _render_access_control(), 400
    response = make_response(_render_access_control(new_invite_code=plaintext_code))
    response.headers["Cache-Control"] = "no-store"
    return response


@access_control_bp.post("/access-control/invitations/<public_id>/revoke")
@login_required
def revoke_invitation(public_id: str):
    _require_admin()
    if not PUBLIC_ID_PATTERN.fullmatch(public_id):
        abort(404)
    now = utc_now()
    result = db.session.execute(
        db.update(Invitation)
        .where(
            Invitation.public_id == public_id,
            Invitation.status == "Active",
            db.or_(Invitation.expires_at.is_(None), Invitation.expires_at > now),
        )
        .values(status="Revoked", revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    if result.rowcount == 1:
        flash("Authorization revoked.", "success")
    else:
        flash("That authorization is no longer active.", "warning")
    return redirect(url_for("access_control.index"))


@access_control_bp.post("/access-control/operators/<callsign>/suspend")
@login_required
def suspend_operator(callsign: str):
    _require_admin()
    operator = find_user_by_callsign(callsign)
    if operator is None:
        abort(404)
    if operator.id == current_user.id:
        flash("You cannot suspend your own account.", "error")
        return redirect(url_for("access_control.index")), 400
    reason = request.form.get("reason", "").strip()
    if (
        len(reason) < 3
        or len(reason) > 300
        or "\x00" in reason
        or HTML_PATTERN.search(reason)
    ):
        flash("Suspension reason must be plain text with 3 to 300 characters.", "error")
        return redirect(url_for("access_control.index")), 400
    if operator.account_state != "Suspended":
        operator.account_state = "Suspended"
        operator.suspended_at = utc_now()
        operator.suspension_reason = reason
        operator.suspended_by_user_id = current_user.id
        operator.auth_version += 1
        db.session.commit()
        from ..realtime import broadcast_online_users, disconnect_user_sessions

        disconnect_user_sessions(operator.id)
        broadcast_online_users()
    flash(f"{operator.username} suspended.", "success")
    return redirect(url_for("access_control.index"))


@access_control_bp.post("/access-control/operators/<callsign>/reactivate")
@login_required
def reactivate_operator(callsign: str):
    _require_admin()
    operator = find_user_by_callsign(callsign)
    if operator is None:
        abort(404)
    if operator.account_state == "Suspended":
        operator.account_state = "Active"
        operator.suspended_at = None
        operator.suspension_reason = None
        operator.suspended_by_user_id = None
        db.session.commit()
    flash(f"{operator.username} reactivated.", "success")
    return redirect(url_for("access_control.index"))
