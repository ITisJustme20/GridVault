"""Server-side profile privacy, block, and trust-control boundaries."""

from __future__ import annotations

import re

from .extensions import db
from .models import (
    Conversation,
    ConversationMember,
    PROFILE_SPECIALTIES,
    REPORT_CATEGORIES,
    User,
    UserBlock,
)


HTML_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
SESSION_AUTH_VERSION_KEY = "gridvault_auth_version"


def find_user_by_callsign(callsign: str) -> User | None:
    value = callsign.strip()
    if not value or len(value) > 30:
        return None
    return db.session.execute(
        db.select(User).where(db.func.lower(User.username) == value.lower())
    ).scalar_one_or_none()


def validate_profile(specialty: str, status_text: str) -> tuple[str | None, str, list[str]]:
    normalized_specialty = specialty.strip()
    normalized_status = status_text.strip()
    errors = []
    if normalized_specialty and normalized_specialty not in PROFILE_SPECIALTIES:
        errors.append("Select a valid specialty.")
    if len(normalized_status) > 120:
        errors.append("Status must contain at most 120 characters.")
    if "\x00" in normalized_status or HTML_PATTERN.search(normalized_status):
        errors.append("Status must be plain text.")
    return normalized_specialty or None, normalized_status, errors


def validate_report(category: str, explanation: str) -> tuple[str, str, list[str]]:
    normalized_category = category.strip()
    normalized_explanation = explanation.strip()
    errors = []
    if normalized_category not in REPORT_CATEGORIES:
        errors.append("Select a valid report reason.")
    if not normalized_explanation or len(normalized_explanation) > 500:
        errors.append("Explanation must contain between 1 and 500 characters.")
    if "\x00" in normalized_explanation or HTML_PATTERN.search(normalized_explanation):
        errors.append("Explanation must be plain text.")
    return normalized_category, normalized_explanation, errors


def block_between(first_user_id: int, second_user_id: int) -> UserBlock | None:
    return db.session.execute(
        db.select(UserBlock).where(
            db.or_(
                db.and_(
                    UserBlock.blocker_id == first_user_id,
                    UserBlock.blocked_id == second_user_id,
                ),
                db.and_(
                    UserBlock.blocker_id == second_user_id,
                    UserBlock.blocked_id == first_user_id,
                ),
            )
        )
    ).scalar_one_or_none()


def block_by(blocker_id: int, blocked_id: int) -> UserBlock | None:
    return db.session.get(UserBlock, (blocker_id, blocked_id))


def blocked_user_ids(user_id: int) -> set[int]:
    rows = db.session.execute(
        db.select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            db.or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    ).all()
    return {
        blocked_id if blocker_id == user_id else blocker_id
        for blocker_id, blocked_id in rows
    }


def shared_group_conversations(viewer_id: int, target_id: int) -> list[Conversation]:
    viewer_groups = db.select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == viewer_id
    )
    return db.session.execute(
        db.select(Conversation)
        .join(
            ConversationMember,
            ConversationMember.conversation_id == Conversation.id,
        )
        .where(
            Conversation.type == "group",
            ConversationMember.user_id == target_id,
            Conversation.id.in_(viewer_groups),
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id)
    ).scalars().all()
