"""Invitation-only access, identity verification, and session routes."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from ..extensions import db
from ..invitations import (
    clear_invitation_failures,
    consume_invitation,
    invitation_attempt_allowed,
    record_invitation_failure,
)
from ..models import User


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Retain the legacy URL without permitting public account creation."""
    return redirect(url_for("auth.access_gate"), code=303)


@auth_bp.route("/access", methods=["GET", "POST"])
def access_gate():
    if current_user.is_authenticated:
        return redirect(url_for("console.dashboard"))

    if request.method == "POST":
        attempt_key = request.remote_addr or "unknown"
        if not invitation_attempt_allowed(attempt_key):
            flash("Access attempts are temporarily limited. Try again later.", "error")
            return render_template("auth/access_gate.html"), 429
        callsign = request.form.get("username", "")
        invite_code = request.form.get("invite_code", "")
        passphrase = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        if passphrase != confirmation:
            record_invitation_failure(attempt_key)
            flash("The passphrases do not match.", "error")
            return render_template("auth/access_gate.html"), 400
        user, error = consume_invitation(invite_code, callsign, passphrase)
        if user is None:
            record_invitation_failure(attempt_key)
            flash(error or "Authorization could not be verified.", "error")
            return render_template("auth/access_gate.html"), 400
        clear_invitation_failures(attempt_key)
        login_user(user)
        return redirect(url_for("auth.orientation"))

    return render_template("auth/access_gate.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("console.dashboard"))

    if request.method == "POST":
        callsign = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.execute(
            db.select(User).where(
                db.func.lower(User.username) == callsign.lower()
            )
        ).scalar_one_or_none()
        if user is None or not check_password_hash(user.password_hash, password):
            flash("Incorrect callsign or passphrase.", "error")
            return render_template("auth/login.html"), 400
        login_user(user)
        if not user.has_seen_orientation:
            return redirect(url_for("auth.orientation"))
        return redirect(url_for("console.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/orientation", methods=["GET", "POST"])
@login_required
def orientation():
    if current_user.has_seen_orientation:
        return redirect(url_for("console.dashboard"))
    if request.method == "POST":
        current_user.has_seen_orientation = True
        db.session.commit()
        return redirect(url_for("console.dashboard"))
    return render_template("auth/orientation.html")


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("auth.login"))
