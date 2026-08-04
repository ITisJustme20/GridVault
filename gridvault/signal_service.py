"""Private, server-authorized Signal Queue derivation and resolution."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import url_for

from .chat_service import (
    accessible_conversations,
    display_name,
    membership_for,
    unread_count,
    user_room,
)
from .extensions import db, socketio
from .file_vault import attachment_can_preview
from .invitations import is_gridvault_admin
from .models import (
    AttachmentOpen,
    ChatAttachment,
    Message,
    OperatorSignal,
    User,
    UserReport,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _latest_unread_message(conversation_id: int, user_id: int, last_read_id: int) -> Message | None:
    return db.session.execute(
        db.select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.id > last_read_id,
            Message.user_id != user_id,
        )
        .order_by(Message.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def active_signals(user: User) -> list[dict[str, object]]:
    """Build one chronological queue from state already authorized to ``user``."""
    if user.account_state != "Active":
        return []

    conversations = [
        item for item in accessible_conversations(user) if item.type in {"direct", "group"}
    ]
    conversation_ids = {item.id for item in conversations}
    queue: list[dict[str, object]] = []

    for conversation in conversations:
        membership = membership_for(conversation.id, user.id)
        if membership is None:
            continue
        count = unread_count(conversation, membership)
        if not count:
            continue
        latest = _latest_unread_message(
            conversation.id,
            user.id,
            membership.last_read_message_id or 0,
        )
        if latest is None:
            continue
        name = display_name(conversation, user.id)
        noun = "transmission" if count == 1 else "transmissions"
        description = (
            f"{count} unread {noun} from {name}"
            if conversation.type == "direct"
            else f"{count} unread {noun} in {name}"
        )
        queue.append(
            {
                "type": "DIRECT" if conversation.type == "direct" else "GROUP",
                "description": description,
                "created_at": latest.created_at,
                "action": "OPEN",
                "action_url": url_for("hub.chat", conversation=conversation.id),
                "action_method": "get",
                "dismiss_url": None,
            }
        )

    if conversation_ids:
        opened_ids = db.select(AttachmentOpen.attachment_id).where(
            AttachmentOpen.user_id == user.id
        )
        attachments = db.session.execute(
            db.select(ChatAttachment)
            .where(
                ChatAttachment.conversation_id.in_(conversation_ids),
                ChatAttachment.uploader_id != user.id,
                ChatAttachment.id.not_in(opened_ids),
            )
            .order_by(ChatAttachment.uploaded_at.desc())
            .limit(100)
        ).scalars().all()
        conversation_by_id = {item.id: item for item in conversations}
        for attachment in attachments:
            conversation = conversation_by_id.get(attachment.conversation_id)
            if conversation is None:
                continue
            location = (
                f"Direct with {display_name(conversation, user.id)}"
                if conversation.type == "direct"
                else f"Group {display_name(conversation, user.id)}"
            )
            previewable = attachment_can_preview(attachment)
            queue.append(
                {
                    "type": "FILE TRANSFER",
                    "description": f"{attachment.original_filename} shared in {location}",
                    "created_at": attachment.uploaded_at,
                    "action": "PREVIEW" if previewable else "OPEN",
                    "action_url": url_for(
                        "hub.preview_attachment" if previewable else "hub.download_attachment",
                        attachment_id=attachment.id,
                    ),
                    "action_method": "get",
                    "dismiss_url": None,
                }
            )

    stored_signals = db.session.execute(
        db.select(OperatorSignal)
        .where(
            OperatorSignal.recipient_user_id == user.id,
            OperatorSignal.resolved_at.is_(None),
        )
        .order_by(OperatorSignal.created_at.desc())
    ).scalars().all()
    for signal in stored_signals:
        if signal.signal_type == "GROUP ACCESS":
            conversation = next(
                (item for item in conversations if item.id == signal.conversation_id),
                None,
            )
            if conversation is None or conversation.type != "group":
                continue
            queue.append(
                {
                    "type": "GROUP ACCESS",
                    "description": f"You were added to {display_name(conversation, user.id)}",
                    "created_at": signal.created_at,
                    "action": "OPEN",
                    "action_url": url_for("hub.chat", conversation=conversation.id),
                    "action_method": "get",
                    "dismiss_url": url_for("signals.dismiss_signal", signal_id=signal.id),
                }
            )
        elif signal.signal_type == "SYSTEM" and signal.description:
            queue.append(
                {
                    "type": "SYSTEM",
                    "description": signal.description,
                    "created_at": signal.created_at,
                    "action": "DISMISS",
                    "action_url": url_for("signals.dismiss_signal", signal_id=signal.id),
                    "action_method": "post",
                    "dismiss_url": None,
                }
            )

    if is_gridvault_admin(user):
        reports = db.session.execute(
            db.select(UserReport)
            .where(UserReport.reviewed_at.is_(None))
            .order_by(UserReport.created_at.desc())
        ).scalars().all()
        for report in reports:
            queue.append(
                {
                    "type": "SYSTEM",
                    "description": "An operator report requires administrator review",
                    "created_at": report.created_at,
                    "action": "REVIEW",
                    "action_url": url_for("signals.review_report", report_id=report.id),
                    "action_method": "post",
                    "dismiss_url": None,
                }
            )

    return sorted(queue, key=lambda item: item["created_at"], reverse=True)


def signal_count(user: User) -> int:
    return len(active_signals(user))


def record_group_access(conversation, users: list[User]) -> None:
    """Create or reactivate one stored signal for each membership event."""
    db.session.flush()
    for user in users:
        existing = db.session.execute(
            db.select(OperatorSignal).where(
                OperatorSignal.recipient_user_id == user.id,
                OperatorSignal.signal_type == "GROUP ACCESS",
                OperatorSignal.conversation_id == conversation.id,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.session.add(
                OperatorSignal(
                    recipient=user,
                    signal_type="GROUP ACCESS",
                    conversation=conversation,
                )
            )
        else:
            existing.created_at = utc_now()
            existing.resolved_at = None


def resolve_group_access(user_id: int, conversation_id: int) -> bool:
    signal = db.session.execute(
        db.select(OperatorSignal).where(
            OperatorSignal.recipient_user_id == user_id,
            OperatorSignal.signal_type == "GROUP ACCESS",
            OperatorSignal.conversation_id == conversation_id,
            OperatorSignal.resolved_at.is_(None),
        )
    ).scalar_one_or_none()
    if signal is None:
        return False
    signal.resolved_at = utc_now()
    db.session.commit()
    return True


def mark_attachment_opened(user_id: int, attachment_id: str) -> bool:
    existing = db.session.get(AttachmentOpen, (user_id, attachment_id))
    if existing is not None:
        return False
    db.session.add(AttachmentOpen(user_id=user_id, attachment_id=attachment_id))
    db.session.commit()
    return True


def administrator_user_ids() -> list[int]:
    users = db.session.execute(
        db.select(User).where(User.account_state == "Active")
    ).scalars().all()
    return [user.id for user in users if is_gridvault_admin(user)]


def broadcast_signal_updates(user_ids: list[int] | set[int]) -> None:
    """Emit only a server-calculated count to each authenticated user room."""
    for user_id in set(user_ids):
        user = db.session.get(User, user_id)
        if user is None or user.account_state != "Active":
            continue
        socketio.emit(
            "signal_queue_updated",
            {"count": signal_count(user)},
            to=user_room(user_id),
        )
