"""Socket.IO events for Hub presence and messaging."""

from flask import request
from flask_login import current_user
from flask_socketio import disconnect, emit

from .extensions import db, socketio
from .models import Message, User


# A user may have multiple browser tabs connected at once.
connected_users: dict[int, dict[str, object]] = {}
sid_to_user_id: dict[str, int] = {}

# Read receipts are intentionally ephemeral and reset with the server process.
message_receipts: dict[int, set[int]] = {}


def get_online_callsigns() -> list[str]:
    callsigns = [
        str(user_data["callsign"])
        for user_data in connected_users.values()
        if user_data["sids"]
    ]
    return sorted(callsigns, key=str.lower)


def broadcast_online_users() -> None:
    socketio.emit("online_users", {"users": get_online_callsigns()})


def get_receipt_callsigns(message_id: int) -> list[str]:
    user_ids = message_receipts.get(message_id, set())
    if not user_ids:
        return []

    users = db.session.execute(
        db.select(User).where(User.id.in_(user_ids))
    ).scalars().all()
    return sorted([user.username for user in users], key=str.lower)


@socketio.on("connect")
def handle_connect():
    if not current_user.is_authenticated:
        return False

    user_id = current_user.id
    sid = request.sid

    if user_id not in connected_users:
        connected_users[user_id] = {
            "callsign": current_user.username,
            "sids": set(),
        }

    connected_users[user_id]["sids"].add(sid)
    sid_to_user_id[sid] = user_id
    broadcast_online_users()


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    user_id = sid_to_user_id.pop(sid, None)
    if user_id is None:
        return

    user_data = connected_users.get(user_id)
    if user_data is None:
        return

    user_data["sids"].discard(sid)
    if not user_data["sids"]:
        connected_users.pop(user_id, None)

    broadcast_online_users()


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

    new_message = Message(body=message_text, user_id=current_user.id)
    db.session.add(new_message)
    db.session.commit()

    emit(
        "receive_message",
        {
            "id": new_message.id,
            "callsign": current_user.username,
            "message": new_message.body,
            "created_at": new_message.created_at.isoformat(),
        },
        broadcast=True,
    )

@socketio.on("typing")
def handle_typing():
    if current_user.is_authenticated:
        emit(
            "user_typing",
            {"callsign": current_user.username},
            broadcast=True,
            include_self=False,
        )


@socketio.on("stop_typing")
def handle_stop_typing():
    if current_user.is_authenticated:
        emit(
            "user_stopped_typing",
            {"callsign": current_user.username},
            broadcast=True,
            include_self=False,
        )


@socketio.on("mark_read")
def handle_mark_read(data):
    if not current_user.is_authenticated or not isinstance(data, dict):
        return

    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        return

    if db.session.get(Message, message_id) is None:
        return

    message_receipts.setdefault(message_id, set()).add(current_user.id)
    emit(
        "read_receipt_update",
        {
            "message_id": message_id,
            "callsigns": get_receipt_callsigns(message_id),
        },
        broadcast=True,
    )
