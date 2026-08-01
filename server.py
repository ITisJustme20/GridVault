import os
from datetime import datetime, timezone

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_socketio import SocketIO, disconnect, emit
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "gridvault-development-key-change-later",
)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///gridvault.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to enter GridVault."

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*",
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(30),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    messages = db.relationship(
        "Message",
        backref="author",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    body = db.Column(
        db.String(500),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
    )


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("chat"))

    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("chat"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(username) < 3 or len(username) > 30:
            flash("Username must contain between 3 and 30 characters.")
            return render_template("register.html")

        if not username.replace("_", "").isalnum():
            flash(
                "Username may contain only letters, numbers, and underscores."
            )
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return render_template("register.html")

        if password != confirm_password:
            flash("The passwords do not match.")
            return render_template("register.html")

        existing_user = db.session.execute(
            db.select(User).where(
                db.func.lower(User.username) == username.lower()
            )
        ).scalar_one_or_none()

        if existing_user:
            flash("That username is already registered.")
            return render_template("register.html")

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
        )

        db.session.add(user)
        db.session.commit()

        login_user(user)

        return redirect(url_for("chat"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("chat"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = db.session.execute(
            db.select(User).where(
                db.func.lower(User.username) == username.lower()
            )
        ).scalar_one_or_none()

        if user is None or not check_password_hash(
            user.password_hash,
            password,
        ):
            flash("Incorrect username or password.")
            return render_template("login.html")

        login_user(user)

        return redirect(url_for("chat"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/chat")
@login_required
def chat():
    saved_messages = db.session.execute(
        db.select(Message)
        .order_by(Message.created_at.desc())
        .limit(100)
    ).scalars().all()

    saved_messages.reverse()

    return render_template(
        "chat.html",
        messages=saved_messages,
    )


@socketio.on("connect")
def handle_connect():
    if not current_user.is_authenticated:
        return False

    print(f"{current_user.username} connected.")


@socketio.on("disconnect")
def handle_disconnect():
    if current_user.is_authenticated:
        print(f"{current_user.username} disconnected.")


@socketio.on("send_message")
def handle_message(data):
    if not current_user.is_authenticated:
        disconnect()
        return

    if not isinstance(data, dict):
        return

    message_text = str(data.get("message", "")).strip()

    if not message_text:
        return

    if len(message_text) > 500:
        emit(
            "message_error",
            {"error": "Messages cannot exceed 500 characters."},
        )
        return

    new_message = Message(
        body=message_text,
        user_id=current_user.id,
    )

    db.session.add(new_message)
    db.session.commit()

    emit(
        "receive_message",
        {
            "id": new_message.id,
            "username": current_user.username,
            "message": new_message.body,
            "created_at": new_message.created_at.isoformat(),
        },
        broadcast=True,
    )


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )