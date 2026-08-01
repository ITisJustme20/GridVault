"""Callsign registration and authentication routes."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("console.dashboard"))

    if request.method == "POST":
        callsign = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(callsign) < 3 or len(callsign) > 30:
            flash("Callsign must contain between 3 and 30 characters.", "error")
            return render_template("auth/register.html")

        if not callsign.replace("_", "").isalnum():
            flash(
                "Callsign may contain only letters, numbers, and underscores.",
                "error",
            )
            return render_template("auth/register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return render_template("auth/register.html")

        if password != confirm_password:
            flash("The passwords do not match.", "error")
            return render_template("auth/register.html")

        existing_user = db.session.execute(
            db.select(User).where(
                db.func.lower(User.username) == callsign.lower()
            )
        ).scalar_one_or_none()

        if existing_user:
            flash("That callsign is already registered.", "error")
            return render_template("auth/register.html")

        user = User(
            username=callsign,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)

        return redirect(url_for("console.dashboard"))

    return render_template("auth/register.html")


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
            flash("Incorrect callsign or password.", "error")
            return render_template("auth/login.html")

        login_user(user)
        return redirect(url_for("console.dashboard"))

    return render_template("auth/login.html")


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("auth.login"))
