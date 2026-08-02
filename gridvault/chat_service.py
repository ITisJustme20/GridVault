"""Authorization and serialization boundaries for GridVault conversations."""

from __future__ import annotations

from sqlalchemy import or_

from .extensions import db
from .models import Conversation, ConversationMember, Message, User
from .trust_service import block_between


GRID_NAME = "GRID"
MAX_GROUP_MEMBERS = 12


def conversation_room(conversation_id: int) -> str:
    return f"conversation:{conversation_id}"


def user_room(user_id: int) -> str:
    return f"user:{user_id}"


def get_grid_conversation() -> Conversation:
    conversation = db.session.execute(
        db.select(Conversation)
        .where(Conversation.type == "grid")
        .order_by(Conversation.id)
    ).scalars().first()
    if conversation is None:
        conversation = Conversation(type="grid", name=GRID_NAME)
        db.session.add(conversation)
        db.session.flush()
    return conversation


def ensure_grid_membership(user: User) -> tuple[Conversation, ConversationMember]:
    grid = get_grid_conversation()
    membership = db.session.get(ConversationMember, (grid.id, user.id))
    if membership is None:
        membership = ConversationMember(conversation=grid, user=user)
        db.session.add(membership)
        db.session.flush()
    return grid, membership


def membership_for(
    conversation_id: int,
    user_id: int,
) -> ConversationMember | None:
    return db.session.get(ConversationMember, (conversation_id, user_id))


def authorized_conversation(
    conversation_id: int,
    user: User,
) -> tuple[Conversation | None, ConversationMember | None]:
    conversation = db.session.get(Conversation, conversation_id)
    if conversation is None:
        return None, None
    if conversation.type == "grid":
        grid, membership = ensure_grid_membership(user)
        if grid.id != conversation.id:
            return None, None
        return conversation, membership
    membership = membership_for(conversation.id, user.id)
    if membership is None:
        return None, None
    if conversation.type == "direct":
        peer_id = next(
            (
                item.user_id
                for item in conversation.memberships
                if item.user_id != user.id
            ),
            None,
        )
        if peer_id is None or block_between(user.id, peer_id) is not None:
            return None, None
    return conversation, membership


def accessible_conversations(user: User) -> list[Conversation]:
    grid, _ = ensure_grid_membership(user)
    member_ids = db.select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == user.id
    )
    conversations = db.session.execute(
        db.select(Conversation)
        .where(or_(Conversation.id == grid.id, Conversation.id.in_(member_ids)))
        .order_by(Conversation.updated_at.desc(), Conversation.id)
    ).scalars().all()
    visible = []
    for conversation in conversations:
        if conversation.type != "direct":
            visible.append(conversation)
            continue
        peer_id = next(
            (
                membership.user_id
                for membership in conversation.memberships
                if membership.user_id != user.id
            ),
            None,
        )
        if peer_id is not None and block_between(user.id, peer_id) is None:
            visible.append(conversation)
    return visible


def direct_key(first_user_id: int, second_user_id: int) -> str:
    low, high = sorted((first_user_id, second_user_id))
    return f"{low}:{high}"


def display_name(conversation: Conversation, viewer_id: int) -> str:
    if conversation.type == "grid":
        return GRID_NAME
    if conversation.type == "direct":
        other = next(
            (
                membership.user.username
                for membership in conversation.memberships
                if membership.user_id != viewer_id
            ),
            "Direct conversation",
        )
        return other
    if conversation.name:
        return conversation.name
    callsigns = sorted(
        (membership.user.username for membership in conversation.memberships),
        key=str.lower,
    )
    return " / ".join(callsigns)


def unread_count(conversation: Conversation, membership: ConversationMember) -> int:
    last_read_id = membership.last_read_message_id or 0
    return db.session.scalar(
        db.select(db.func.count(Message.id)).where(
            Message.conversation_id == conversation.id,
            Message.id > last_read_id,
            Message.user_id != membership.user_id,
        )
    ) or 0


def receipt_callsigns(message: Message) -> list[str]:
    memberships = db.session.execute(
        db.select(ConversationMember)
        .where(
            ConversationMember.conversation_id == message.conversation_id,
            ConversationMember.user_id != message.user_id,
            ConversationMember.last_read_message_id >= message.id,
        )
    ).scalars().all()
    return sorted(
        (membership.user.username for membership in memberships),
        key=str.lower,
    )


def serialize_message(message: Message) -> dict[str, object]:
    payload = {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "callsign": message.author.username,
        "message": message.body,
        "created_at": message.created_at.isoformat(),
        "read_by": receipt_callsigns(message),
    }
    if message.attachment is not None:
        from .file_vault import serialize_attachment

        payload["attachment"] = serialize_attachment(message.attachment)
    else:
        payload["attachment"] = None
    return payload
