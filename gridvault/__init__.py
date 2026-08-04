"""GridVault application factory."""

from __future__ import annotations

import secrets
from pathlib import Path

from flask import Flask, request, session

from .config import Config
from .extensions import csrf, db, login_manager, socketio
from .identity_disc import configure_identity_disc_secret


def _cors_origins(value: str | None):
    if not value:
        return None
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def create_app(test_config: dict | None = None) -> Flask:
    project_root = Path(__file__).resolve().parent.parent
    instance_path = project_root / "instance"

    app = Flask(
        __name__,
        instance_path=str(instance_path),
        instance_relative_config=True,
    )
    app.config.from_object(Config)

    if test_config is None:
        Config.validate()
    else:
        app.config.update(test_config)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "Using an ephemeral development SECRET_KEY. Set SECRET_KEY to "
            "keep sessions valid across restarts."
        )

    instance_path.mkdir(parents=True, exist_ok=True)
    configure_identity_disc_secret(app, instance_path)
    if not app.config.get("DESIGN_UPLOAD_FOLDER"):
        app.config["DESIGN_UPLOAD_FOLDER"] = str(instance_path / "design_uploads")
    if not app.config.get("CHAT_UPLOAD_FOLDER"):
        app.config["CHAT_UPLOAD_FOLDER"] = str(instance_path / "chat_uploads")
    app.config.setdefault("DESIGN_UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
    app.config.setdefault("CHAT_UPLOAD_MAX_BYTES", 25 * 1024 * 1024)
    app.config["MAX_CONTENT_LENGTH"] = max(
        app.config["DESIGN_UPLOAD_MAX_BYTES"],
        app.config["CHAT_UPLOAD_MAX_BYTES"],
    ) + 1024 * 1024

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio.init_app(
        app,
        async_mode="threading",
        cors_allowed_origins=_cors_origins(
            app.config.get("SOCKETIO_CORS_ALLOWED_ORIGINS")
        ),
    )

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to enter GridVault."
    login_manager.login_message_category = "warning"

    from .blueprints.access_control import access_control_bp
    from .blueprints.auth import auth_bp
    from .blueprints.console import console_bp
    from .blueprints.design_lab import design_lab_bp
    from .blueprints.hub import hub_bp
    from .blueprints.live_grid import live_grid_bp
    from .blueprints.modules import modules_bp
    from .blueprints.projects import projects_bp
    from .blueprints.profiles import profiles_bp
    from .invitations import is_gridvault_admin
    from .models import User
    from .trust_service import SESSION_AUTH_VERSION_KEY
    from .schema import ensure_schema
    from . import realtime  # noqa: F401 - registers Socket.IO handlers

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None
        if user is None or user.account_state != "Active":
            return None
        session_version = session.get(SESSION_AUTH_VERSION_KEY)
        if session_version is None and user.auth_version == 0:
            session[SESSION_AUTH_VERSION_KEY] = 0
        elif session_version != user.auth_version:
            return None
        return user

    app.register_blueprint(auth_bp)
    app.register_blueprint(access_control_bp)
    app.register_blueprint(console_bp)
    app.register_blueprint(hub_bp)
    app.register_blueprint(live_grid_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(design_lab_bp)
    app.register_blueprint(modules_bp)
    app.register_blueprint(profiles_bp)

    app.jinja_env.globals["is_gridvault_admin"] = is_gridvault_admin

    @app.context_processor
    def inject_grid_presence_sector():
        sector = "ACTIVE"
        if request.blueprint == "design_lab":
            sector = "VC BOARD"
        elif request.blueprint in {"profiles", "access_control"}:
            sector = "ACCESS"
        return {"grid_presence_sector": sector}

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.socket.io; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'",
        )
        return response

    ensure_schema(app)

    return app
