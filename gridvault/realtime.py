"""Authorized Socket.IO presence, messaging, typing, and read-state events."""

from __future__ import annotations

import re
import secrets
import time
from collections import deque
from datetime import datetime, timezone
from itertools import count

from flask import current_app, request
from flask_login import current_user
from flask_socketio import disconnect, emit, join_room

from .chat_service import (
    accessible_conversations,
    authorized_conversation,
    conversation_room,
    ensure_grid_membership,
    receipt_callsigns,
    serialize_message,
    user_room,
)
from .extensions import db, socketio
from .models import Message, User
from .trust_service import blocked_user_ids


connected_users: dict[int, dict[str, object]] = {}
sid_to_user_id: dict[str, int] = {}
# Compatibility alias retained for older test and extension imports. Read
# state now lives durably on ConversationMember rather than in this mapping.
message_receipts: dict[int, set[int]] = {}
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
LIVE_GRID_ROOM = "live-grid"
LIVE_GRID_SECTORS = frozenset(
    {"GRID", "DIRECT", "GROUPS", "VC BOARD", "FILE VAULT", "ACCESS", "ACTIVE"}
)
LIVE_GRID_PULSE_TYPES = frozenset(
    {"TRANSMISSION", "FILE TRANSFER", "BOARD UPDATE", "OPERATOR ONLINE", "OPERATOR OFFLINE"}
)
LIVE_GRID_ACTIVITY_TTL_SECONDS = 30
PRESENCE_DISCONNECT_GRACE_SECONDS = 2
recent_grid_activity: deque[dict[str, object]] = deque(maxlen=18)
presence_sequence = count(1)


def _current_sector(user_data: dict[str, object]) -> str:
    activity = user_data.get("activity", {})
    sectors = user_data.get("sectors", {})
    if not isinstance(activity, dict) or not activity:
        return "ACTIVE"
    sid = max(activity, key=activity.get)
    sector = sectors.get(sid, "ACTIVE") if isinstance(sectors, dict) else "ACTIVE"
    return str(sector) if sector in LIVE_GRID_SECTORS else "ACTIVE"


def _live_grid_operators(viewer_id: int) -> list[dict[str, str]]:
    hidden_ids = blocked_user_ids(viewer_id)
    operators = []
    for user_id, user_data in connected_users.items():
        if not user_data["sids"] or user_id in hidden_ids:
            continue
        user = db.session.get(User, user_id)
        if user is None or user.account_state != "Active":
            continue
        sector = _current_sector(user_data)
        if user_id != viewer_id and user.presence_visibility != "Sector":
            sector = "ACTIVE"
        operators.append({"callsign": user.username, "sector": sector})
    return sorted(operators, key=lambda item: item["callsign"].lower())


def _recent_activity() -> list[dict[str, str]]:
    cutoff = time.monotonic() - LIVE_GRID_ACTIVITY_TTL_SECONDS
    while recent_grid_activity and recent_grid_activity[0]["recorded_at"] < cutoff:
        recent_grid_activity.popleft()
    return [
        {
            "id": str(item["id"]),
            "type": str(item["type"]),
            "sector": str(item["sector"]),
            "created_at": str(item["created_at"]),
        }
        for item in recent_grid_activity
    ]


def record_grid_activity(activity_type: str, sector: str) -> dict[str, str] | None:
    """Publish a short-lived abstract pulse without actor or resource metadata."""
    if activity_type not in LIVE_GRID_PULSE_TYPES or sector not in LIVE_GRID_SECTORS:
        return None
    pulse = {
        "id": secrets.token_hex(6),
        "type": activity_type,
        "sector": sector,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recorded_at": time.monotonic(),
    }
    recent_grid_activity.append(pulse)
    public_pulse = {key: str(pulse[key]) for key in ("id", "type", "sector", "created_at")}
    socketio.emit("live_grid_pulse", public_pulse, to=LIVE_GRID_ROOM)
    return public_pulse


def broadcast_live_grid_presence() -> None:
    for viewer_id, user_data in list(connected_users.items()):
        if not user_data["sids"]:
            continue
        viewer = db.session.get(User, viewer_id)
        if viewer is None or viewer.account_state != "Active":
            continue
        socketio.emit(
            "live_grid_presence",
            {"operators": _live_grid_operators(viewer_id)},
            to=user_room(viewer_id),
        )


def get_online_callsigns(viewer_id: int | None = None) -> list[str]:
    hidden_ids = blocked_user_ids(viewer_id) if viewer_id is not None else set()
    callsigns = [
        str(user_data["callsign"])
        for user_id, user_data in connected_users.items()
        if user_data["sids"]
        and user_id not in hidden_ids
        and (
            (user := db.session.get(User, user_id)) is not None
            and user.account_state == "Active"
        )
    ]
    return sorted(callsigns, key=str.lower)


def broadcast_online_users() -> None:
    for user_id, user_data in list(connected_users.items()):
        if not user_data["sids"]:
            continue
        socketio.emit(
            "online_users",
            {"users": get_online_callsigns(user_id)},
            to=user_room(user_id),
        )
    broadcast_live_grid_presence()


def disconnect_user_sessions(user_id: int) -> None:
    """Invalidate active Socket.IO connections after account suspension."""
    user_data = connected_users.get(user_id)
    if user_data is None:
        return
    for sid in list(user_data["sids"]):
        socketio.server.disconnect(sid, namespace="/")


def _expire_disconnected_user(user_id: int, token: str, app) -> None:
    socketio.sleep(PRESENCE_DISCONNECT_GRACE_SECONDS)
    with app.app_context():
        user_data = connected_users.get(user_id)
        if (
            user_data is None
            or user_data["sids"]
            or user_data.get("disconnect_token") != token
        ):
            return
        connected_users.pop(user_id, None)
        record_grid_activity("OPERATOR OFFLINE", "ACTIVE")
        broadcast_online_users()


def _active_socket_user() -> bool:
    if not current_user.is_authenticated:
        disconnect()
        return False
    user = db.session.get(User, current_user.id)
    if user is None or user.account_state != "Active":
        disconnect()
        return False
    return True


def _conversation_id(data, *, default_grid=False) -> int | None:
    raw_value = data.get("conversation_id") if isinstance(data, dict) else None
    if raw_value is None and default_grid:
        grid, _ = ensure_grid_membership(current_user)
        db.session.commit()
        return grid.id
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _authorized(data, *, default_grid=False):
    conversation_id = _conversation_id(data, default_grid=default_grid)
    if conversation_id is None:
        emit("conversation_error", {"error": "Select a valid conversation."})
        return None, None
    conversation, membership = authorized_conversation(conversation_id, current_user)
    if conversation is None or membership is None:
        emit("conversation_error", {"error": "Conversation access denied."})
        return None, None
    return conversation, membership


@socketio.on("connect")
def handle_connect():
    if not _active_socket_user():
        return False

    user_id = current_user.id
    sid = request.sid
    ensure_grid_membership(current_user)
    db.session.commit()
    join_room(user_room(user_id))
    for conversation in accessible_conversations(current_user):
        join_room(conversation_room(conversation.id))

    was_offline = user_id not in connected_users
    if was_offline:
        connected_users[user_id] = {
            "callsign": current_user.username,
            "sids": set(),
            "sectors": {},
            "activity": {},
            "disconnect_token": None,
        }
    connected_users[user_id]["disconnect_token"] = None
    connected_users[user_id]["sids"].add(sid)
    connected_users[user_id]["sectors"][sid] = "ACTIVE"
    connected_users[user_id]["activity"][sid] = next(presence_sequence)
    sid_to_user_id[sid] = user_id
    if was_offline:
        record_grid_activity("OPERATOR ONLINE", "ACTIVE")
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
    user_data.get("sectors", {}).pop(sid, None)
    user_data.get("activity", {}).pop(sid, None)
    if not user_data["sids"]:
        token = secrets.token_hex(8)
        user_data["disconnect_token"] = token
        socketio.start_background_task(
            _expire_disconnected_user,
            user_id,
            token,
            current_app._get_current_object(),
        )
        return
    broadcast_online_users()


@socketio.on("presence_sector")
def handle_presence_sector(data):
    if not _active_socket_user():
        return
    sector = data.get("sector") if isinstance(data, dict) else None
    if sector not in LIVE_GRID_SECTORS:
        emit("presence_error", {"error": "Select a valid Grid sector."})
        return
    user_data = connected_users.get(current_user.id)
    if user_data is None or request.sid not in user_data["sids"]:
        return
    user_data["sectors"][request.sid] = sector
    user_data["activity"][request.sid] = next(presence_sequence)
    broadcast_live_grid_presence()
    emit("presence_updated", {"sector": sector})


@socketio.on("live_grid_subscribe")
def handle_live_grid_subscribe():
    if not _active_socket_user():
        return
    join_room(LIVE_GRID_ROOM)
    emit(
        "live_grid_state",
        {
            "operators": _live_grid_operators(current_user.id),
            "pulses": _recent_activity(),
        },
    )


@socketio.on("subscribe_conversation")
def handle_subscribe(data):
    if not _active_socket_user():
        return
    conversation, _ = _authorized(data)
    if conversation is None:
        return
    join_room(conversation_room(conversation.id))
    emit("conversation_subscribed", {"conversation_id": conversation.id})


@socketio.on("send_message")
def handle_message(data):
    if not _active_socket_user():
        return
    if not isinstance(data, dict):
        emit("message_error", {"error": "The message payload is invalid."})
        return
    conversation, _ = _authorized(data, default_grid=True)
    if conversation is None:
        return

    message_text = str(data.get("message", "")).strip()
    if not message_text:
        emit("message_error", {"error": "Messages cannot be empty."})
        return
    if len(message_text) > 500 or "\x00" in message_text:
        emit("message_error", {"error": "Messages must be plain text with at most 500 characters."})
        return
    client_id = str(data.get("client_id", "")).strip()
    if client_id and not CLIENT_ID_PATTERN.fullmatch(client_id):
        emit("message_error", {"error": "The pending message identifier is invalid."})
        return

    new_message = Message(
        body=message_text,
        user_id=current_user.id,
        conversation_id=conversation.id,
    )
    conversation.updated_at = datetime.now(timezone.utc)
    db.session.add(new_message)
    db.session.commit()
    payload = serialize_message(new_message)
    payload["client_id"] = client_id
    socketio.emit(
        "receive_message",
        payload,
        to=conversation_room(conversation.id),
    )
    conversation_sector = {
        "grid": "GRID",
        "direct": "DIRECT",
        "group": "GROUPS",
    }[conversation.type]
    record_grid_activity("TRANSMISSION", conversation_sector)
    emit(
        "message_ack",
        {
            "client_id": client_id,
            "message_id": new_message.id,
            "conversation_id": conversation.id,
        },
    )


def broadcast_message(message: Message, client_id: str = "") -> dict[str, object]:
    """Publish a committed HTTP-created message to its authorized room."""
    payload = serialize_message(message)
    payload["client_id"] = client_id
    socketio.emit(
        "receive_message",
        payload,
        to=conversation_room(message.conversation_id),
    )
    return payload


def _typing_event(data, event_name: str):
    if not _active_socket_user():
        return
    conversation, _ = _authorized(data, default_grid=True)
    if conversation is None:
        return
    emit(
        event_name,
        {
            "conversation_id": conversation.id,
            "callsign": current_user.username,
        },
        to=conversation_room(conversation.id),
        include_self=False,
    )


@socketio.on("typing")
def handle_typing(data=None):
    _typing_event(data or {}, "user_typing")


@socketio.on("stop_typing")
def handle_stop_typing(data=None):
    _typing_event(data or {}, "user_stopped_typing")


@socketio.on("mark_read")
def handle_mark_read(data):
    if not _active_socket_user() or not isinstance(data, dict):
        return
    conversation, membership = _authorized(data, default_grid=True)
    if conversation is None or membership is None:
        return
    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        emit("conversation_error", {"error": "Read state is invalid."})
        return
    message = db.session.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id:
        emit("conversation_error", {"error": "Read state is invalid."})
        return
    if membership.last_read_message_id is None or message_id > membership.last_read_message_id:
        membership.last_read_message_id = message_id
        db.session.commit()
    callsigns = receipt_callsigns(message)
    socketio.emit(
        "read_receipt_update",
        {
            "conversation_id": conversation.id,
            "message_id": message.id,
            "callsigns": callsigns,
        },
        to=conversation_room(conversation.id),
    )
