"""Authenticated HTTP routes for Grid, Direct, and Group conversations."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..chat_service import (
    MAX_GROUP_MEMBERS,
    accessible_conversations,
    authorized_conversation,
    direct_key,
    display_name,
    ensure_grid_membership,
    receipt_callsigns,
    unread_count,
    user_room,
)
from ..extensions import db, socketio
from ..file_vault import (
    FileValidationError,
    allowed_extensions,
    attachment_can_preview,
    attachment_path,
    discard_private_file,
    human_file_size,
    serialize_attachment,
    store_private_file,
    validate_upload,
)
from ..models import ChatAttachment, Conversation, ConversationMember, Message, User
from ..trust_service import block_between


hub_bp = Blueprint("hub", __name__)
HTML_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _callsigns(raw_value: str) -> list[str]:
    values = []
    seen = set()
    for value in raw_value.split(","):
        callsign = value.strip()
        key = callsign.lower()
        if callsign and key not in seen:
            values.append(callsign)
            seen.add(key)
    return values


def _users_for_callsigns(callsigns: list[str]) -> tuple[list[User], list[str]]:
    if not callsigns:
        return [], []
    requested = {callsign.lower(): callsign for callsign in callsigns}
    users = db.session.execute(
        db.select(User).where(
            db.func.lower(User.username).in_(requested),
            User.account_state == "Active",
        )
    ).scalars().all()
    found = {user.username.lower() for user in users}
    missing = [original for key, original in requested.items() if key not in found]
    users.sort(key=lambda user: user.username.lower())
    return users, missing


def _notify_conversation_members(
    conversation: Conversation,
    *,
    exclude_user_id: int | None = None,
) -> None:
    for membership in conversation.memberships:
        if membership.user_id == exclude_user_id:
            continue
        socketio.emit(
            "conversation_list_changed",
            {"conversation_id": conversation.id},
            to=user_room(membership.user_id),
        )


@hub_bp.get("/hub")
@hub_bp.get("/chat")
@login_required
def chat():
    grid, _ = ensure_grid_membership(current_user)
    db.session.commit()
    conversations = accessible_conversations(current_user)

    requested_id = request.args.get("conversation", "").strip()
    if requested_id:
        if not requested_id.isdigit():
            abort(400)
        active, active_membership = authorized_conversation(
            int(requested_id),
            current_user,
        )
        if active is None:
            abort(403)
    else:
        active, active_membership = authorized_conversation(grid.id, current_user)

    direct_conversations = [item for item in conversations if item.type == "direct"]
    group_conversations = [item for item in conversations if item.type == "group"]
    unread_counts = {
        item.id: unread_count(
            item,
            next(
                membership
                for membership in item.memberships
                if membership.user_id == current_user.id
            ),
        )
        for item in conversations
    }
    saved_messages = db.session.execute(
        db.select(Message)
        .where(Message.conversation_id == active.id)
        .order_by(Message.created_at.desc())
        .limit(100)
    ).scalars().all()
    saved_messages.reverse()
    receipt_map = {
        message.id: receipt_callsigns(message)
        for message in saved_messages
        if message.user_id == current_user.id
    }
    active_attachments = db.session.execute(
        db.select(ChatAttachment)
        .where(ChatAttachment.conversation_id == active.id)
        .order_by(ChatAttachment.uploaded_at.desc())
        .limit(100)
    ).scalars().all() if active.type in {"direct", "group"} else []
    operators = db.session.execute(
        db.select(User)
        .where(
            User.id != current_user.id,
            User.account_state == "Active",
        )
        .order_by(db.func.lower(User.username))
    ).scalars().all()
    active_members = sorted(
        (membership.user for membership in active.memberships),
        key=lambda user: user.username.lower(),
    )
    direct_peer = next(
        (user for user in active_members if user.id != current_user.id),
        None,
    ) if active.type == "direct" else None
    return render_template(
        "hub/chat.html",
        grid=grid,
        active=active,
        active_membership=active_membership,
        active_name=display_name(active, current_user.id),
        active_members=active_members,
        direct_peer=direct_peer,
        direct_conversations=direct_conversations,
        group_conversations=group_conversations,
        display_name=display_name,
        unread_counts=unread_counts,
        messages=saved_messages,
        receipt_map=receipt_map,
        operators=operators,
        active_attachments=active_attachments,
        attachment_can_preview=attachment_can_preview,
        human_file_size=human_file_size,
        attachment_accept=",".join(f".{extension}" for extension in allowed_extensions()),
        attachment_max_size=human_file_size(current_app.config["CHAT_UPLOAD_MAX_BYTES"]),
    )


def _authorized_attachment(attachment_id: str) -> ChatAttachment:
    if not re.fullmatch(r"[0-9a-f]{32}", attachment_id):
        abort(404)
    attachment = db.session.get(ChatAttachment, attachment_id)
    if attachment is None:
        abort(404)
    conversation, membership = authorized_conversation(
        attachment.conversation_id,
        current_user,
    )
    if conversation is None or membership is None or conversation.type == "grid":
        abort(403)
    return attachment


def _secure_file_response(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


@hub_bp.post("/chat/conversations/<int:conversation_id>/attachments")
@login_required
def upload_attachment(conversation_id: int):
    conversation, membership = authorized_conversation(conversation_id, current_user)
    if conversation is None or membership is None:
        return jsonify({"ok": False, "error": "Conversation access denied."}), 403
    if conversation.type not in {"direct", "group"}:
        return jsonify({"ok": False, "error": "Files cannot be shared in GRID."}), 400
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"ok": False, "error": "Choose a file to attach."}), 400
    message_text = request.form.get("message", "").strip()
    if len(message_text) > 500 or "\x00" in message_text:
        return jsonify({
            "ok": False,
            "error": "Messages must be plain text with at most 500 characters.",
        }), 400
    client_id = request.form.get("client_id", "").strip()
    if client_id and not CLIENT_ID_PATTERN.fullmatch(client_id):
        return jsonify({"ok": False, "error": "The pending message identifier is invalid."}), 400
    try:
        data, original_filename, extension, rule = validate_upload(
            uploaded,
            current_app.config["CHAT_UPLOAD_MAX_BYTES"],
        )
    except FileValidationError as error:
        return jsonify({"ok": False, "error": str(error)}), 400

    try:
        storage_key = store_private_file(data, extension)
    except (OSError, RuntimeError):
        current_app.logger.error("Private chat attachment storage is unavailable.")
        return jsonify({"ok": False, "error": "The upload could not be completed."}), 500
    try:
        message = Message(
            body=message_text,
            author=current_user,
            conversation=conversation,
        )
        db.session.add(message)
        db.session.flush()
        attachment = ChatAttachment(
            id=uuid.uuid4().hex,
            conversation=conversation,
            message=message,
            uploader=current_user,
            original_filename=original_filename,
            storage_key=storage_key,
            byte_size=len(data),
            detected_mime_type=rule.mime_type,
            category=rule.category,
        )
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.add(attachment)
        db.session.commit()
    except Exception:
        db.session.rollback()
        discard_private_file(storage_key)
        current_app.logger.error("Chat attachment transaction failed.")
        return jsonify({"ok": False, "error": "The upload could not be completed."}), 500

    from ..realtime import broadcast_message

    payload = broadcast_message(message, client_id)
    return jsonify({"ok": True, "message": payload}), 201


@hub_bp.get("/chat/conversations/<int:conversation_id>/files")
@login_required
def conversation_files(conversation_id: int):
    conversation, membership = authorized_conversation(conversation_id, current_user)
    if conversation is None or membership is None or conversation.type == "grid":
        abort(403)
    attachments = db.session.execute(
        db.select(ChatAttachment)
        .where(ChatAttachment.conversation_id == conversation.id)
        .order_by(ChatAttachment.uploaded_at.desc())
        .limit(100)
    ).scalars().all()
    return jsonify({"files": [serialize_attachment(item) for item in attachments]})


@hub_bp.get("/chat/attachments/<attachment_id>/metadata")
@login_required
def attachment_metadata(attachment_id: str):
    return jsonify({"attachment": serialize_attachment(_authorized_attachment(attachment_id))})


@hub_bp.get("/chat/attachments/<attachment_id>/preview")
@login_required
def preview_attachment(attachment_id: str):
    attachment = _authorized_attachment(attachment_id)
    if not attachment_can_preview(attachment):
        abort(404)
    try:
        path = attachment_path(attachment)
    except FileNotFoundError:
        abort(404)
    if attachment.category == "image":
        response = send_file(
            path,
            mimetype=attachment.detected_mime_type,
            as_attachment=False,
            download_name=attachment.original_filename,
            conditional=True,
            max_age=0,
        )
    else:
        text_content = path.read_bytes().decode("utf-8-sig")
        response = Response(text_content, content_type="text/plain; charset=utf-8")
        response.headers.set(
            "Content-Disposition",
            "inline",
            filename=attachment.original_filename,
        )
    return _secure_file_response(response)


@hub_bp.get("/chat/attachments/<attachment_id>/download")
@login_required
def download_attachment(attachment_id: str):
    attachment = _authorized_attachment(attachment_id)
    try:
        path = attachment_path(attachment)
    except FileNotFoundError:
        abort(404)
    response = send_file(
        path,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=attachment.original_filename,
        conditional=True,
        max_age=0,
    )
    return _secure_file_response(response)


@hub_bp.post("/chat/conversations")
@login_required
def create_conversation():
    callsigns = _callsigns(request.form.get("callsigns", ""))
    if not callsigns:
        flash("Select at least one other callsign.", "error")
        return redirect(url_for("hub.chat"))
    if len(callsigns) >= MAX_GROUP_MEMBERS:
        flash(f"Groups may contain at most {MAX_GROUP_MEMBERS} operators.", "error")
        return redirect(url_for("hub.chat"))
    if current_user.username.lower() in {value.lower() for value in callsigns}:
        flash("You are already included as the conversation creator.", "error")
        return redirect(url_for("hub.chat"))

    participants, missing = _users_for_callsigns(callsigns)
    if missing:
        flash(f"Unknown callsign: {', '.join(missing)}.", "error")
        return redirect(url_for("hub.chat"))

    if len(participants) == 1:
        if block_between(current_user.id, participants[0].id) is not None:
            flash("Direct conversation is unavailable.", "error")
            return redirect(url_for("hub.chat"))
        key = direct_key(current_user.id, participants[0].id)
        conversation = db.session.execute(
            db.select(Conversation).where(
                Conversation.type == "direct",
                Conversation.direct_key == key,
            )
        ).scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(
                type="direct",
                direct_key=key,
                creator=current_user,
            )
            conversation.memberships = [
                ConversationMember(user=current_user),
                ConversationMember(user=participants[0]),
            ]
            db.session.add(conversation)
            db.session.commit()
            _notify_conversation_members(
                conversation,
                exclude_user_id=current_user.id,
            )
        return redirect(url_for("hub.chat", conversation=conversation.id))

    group_name = request.form.get("group_name", "").strip()
    if len(group_name) > 80 or HTML_PATTERN.search(group_name):
        flash("Group names must be plain text with at most 80 characters.", "error")
        return redirect(url_for("hub.chat"))
    conversation = Conversation(
        type="group",
        name=group_name or None,
        creator=current_user,
    )
    conversation.memberships = [
        ConversationMember(user=current_user),
        *(ConversationMember(user=user) for user in participants),
    ]
    db.session.add(conversation)
    db.session.commit()
    _notify_conversation_members(
        conversation,
        exclude_user_id=current_user.id,
    )
    return redirect(url_for("hub.chat", conversation=conversation.id))


@hub_bp.post("/chat/conversations/<int:conversation_id>/members")
@login_required
def add_group_member(conversation_id: int):
    conversation, _ = authorized_conversation(conversation_id, current_user)
    if conversation is None:
        abort(403)
    if conversation.type != "group" or conversation.creator_id != current_user.id:
        abort(403)
    if len(conversation.memberships) >= MAX_GROUP_MEMBERS:
        flash(f"Groups may contain at most {MAX_GROUP_MEMBERS} operators.", "error")
        return redirect(url_for("hub.chat", conversation=conversation.id))

    callsign = request.form.get("callsign", "").strip()
    user = db.session.execute(
        db.select(User).where(
            db.func.lower(User.username) == callsign.lower(),
            User.account_state == "Active",
        )
    ).scalar_one_or_none()
    if user is None:
        flash("That callsign does not exist.", "error")
    elif user.id == current_user.id or any(
        membership.user_id == user.id for membership in conversation.memberships
    ):
        flash("That callsign is already in this group.", "error")
    else:
        conversation.memberships.append(ConversationMember(user=user))
        conversation.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        _notify_conversation_members(
            conversation,
            exclude_user_id=current_user.id,
        )
        flash(f"{user.username} joined the group.", "success")
    return redirect(url_for("hub.chat", conversation=conversation.id))


@hub_bp.post("/chat/conversations/<int:conversation_id>/leave")
@login_required
def leave_group(conversation_id: int):
    conversation, membership = authorized_conversation(conversation_id, current_user)
    if conversation is None or membership is None:
        abort(403)
    if conversation.type != "group":
        abort(400)
    db.session.delete(membership)
    conversation.updated_at = datetime.now(timezone.utc)
    remaining_user_ids = [
        item.user_id for item in conversation.memberships if item.user_id != current_user.id
    ]
    db.session.commit()
    for user_id in remaining_user_ids:
        socketio.emit(
            "conversation_list_changed",
            {"conversation_id": conversation.id},
            to=user_room(user_id),
        )
    flash("You left the group. Its existing history remains preserved.", "success")
    return redirect(url_for("hub.chat"))
