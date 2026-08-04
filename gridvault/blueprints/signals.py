"""Authenticated, privacy-filtered Signal Queue routes."""

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..invitations import is_gridvault_admin
from ..models import OperatorSignal, UserReport
from ..signal_service import (
    active_signals,
    administrator_user_ids,
    broadcast_signal_updates,
    utc_now,
)


signals_bp = Blueprint("signals", __name__)


@signals_bp.get("/signals")
@login_required
def index():
    return render_template("signals/index.html", signals=active_signals(current_user))


@signals_bp.post("/signals/<int:signal_id>/dismiss")
@login_required
def dismiss_signal(signal_id: int):
    signal = db.session.get(OperatorSignal, signal_id)
    if signal is None:
        abort(404)
    if signal.recipient_user_id != current_user.id:
        abort(403)
    if signal.resolved_at is None:
        signal.resolved_at = utc_now()
        db.session.commit()
        broadcast_signal_updates({current_user.id})
    flash("Signal dismissed.", "success")
    return redirect(url_for("signals.index"))


@signals_bp.post("/signals/reports/<int:report_id>/review")
@login_required
def review_report(report_id: int):
    if not is_gridvault_admin(current_user):
        abort(403)
    report = db.session.get(UserReport, report_id)
    if report is None:
        abort(404)
    if report.reviewed_at is None:
        report.reviewed_at = utc_now()
        report.reviewed_by_user_id = current_user.id
        db.session.commit()
        broadcast_signal_updates(administrator_user_ids())
    flash("Report review recorded.", "success")
    return redirect(url_for("access_control.index", _anchor="operator-reports"))
