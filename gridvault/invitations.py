"""Secure invitation issuance, authorization, and atomic consumption."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import Invitation, User


INVITATION_CODE_PATTERN = re.compile(r"^GV-[A-F0-9]{40}$")
MAX_INVITATION_FAILURES = 8
INVITATION_FAILURE_WINDOW_SECONDS = 15 * 60
_failed_invitation_attempts: dict[str, deque[float]] = defaultdict(deque)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_callsign(raw_callsign: str) -> tuple[str | None, str | None]:
    callsign = raw_callsign.strip().upper()
    if len(callsign) < 3 or len(callsign) > 30:
        return None, "Callsign must contain between 3 and 30 characters."
    if not callsign.replace("_", "").isalnum() or not callsign.isascii():
        return None, "Callsign may contain only letters, numbers, and underscores."
    return callsign, None


def normalize_invitation_code(raw_code: str) -> str:
    return raw_code.strip().upper()


def invitation_code_hash(raw_code: str) -> str:
    normalized = normalize_invitation_code(raw_code)
    return hashlib.sha256(normalized.encode("ascii", "ignore")).hexdigest()


def invitation_label(invitation: Invitation) -> str:
    return f"INV-{invitation.code_hash[:8].upper()}"


def is_gridvault_admin(user: User) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    configured = {
        callsign.strip().lower()
        for callsign in current_app.config.get("GRIDVAULT_ADMIN_CALLSIGNS", "").split(",")
        if callsign.strip()
    }
    return bool(user.is_admin or user.username.lower() in configured)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def invitation_is_expired(invitation: Invitation, now: datetime | None = None) -> bool:
    expiration = _aware(invitation.expires_at)
    return expiration is not None and expiration <= (now or utc_now())


def refresh_expired_invitations() -> None:
    now = utc_now()
    db.session.execute(
        db.update(Invitation)
        .where(
            Invitation.status == "Active",
            Invitation.expires_at.is_not(None),
            Invitation.expires_at <= now,
        )
        .values(status="Expired")
    )
    db.session.commit()


def issue_invitation(
    creator: User,
    *,
    reserved_callsign: str = "",
    expires_in: timedelta | None = None,
) -> tuple[Invitation, str]:
    normalized_reserved = None
    if reserved_callsign.strip():
        normalized_reserved, error = normalize_callsign(reserved_callsign)
        if error:
            raise ValueError(error)
    plaintext_code = f"GV-{secrets.token_hex(20).upper()}"
    invitation = Invitation(
        public_id=uuid.uuid4().hex,
        code_hash=invitation_code_hash(plaintext_code),
        reserved_callsign=normalized_reserved,
        creator=creator,
        expires_at=utc_now() + expires_in if expires_in else None,
        status="Active",
    )
    db.session.add(invitation)
    db.session.commit()
    return invitation, plaintext_code


def invitation_attempt_allowed(key: str) -> bool:
    now = time.monotonic()
    attempts = _failed_invitation_attempts[key]
    while attempts and attempts[0] <= now - INVITATION_FAILURE_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) < MAX_INVITATION_FAILURES


def record_invitation_failure(key: str) -> None:
    _failed_invitation_attempts[key].append(time.monotonic())


def clear_invitation_failures(key: str) -> None:
    _failed_invitation_attempts.pop(key, None)


def reset_invitation_attempts() -> None:
    """Clear process-local throttling state for isolated test applications."""
    _failed_invitation_attempts.clear()


def consume_invitation(
    raw_code: str,
    raw_callsign: str,
    passphrase: str,
) -> tuple[User | None, str | None]:
    callsign, callsign_error = normalize_callsign(raw_callsign)
    if callsign_error:
        return None, callsign_error
    if len(passphrase) < 12 or len(passphrase) > 256:
        return None, "Passphrase must contain between 12 and 256 characters."

    normalized_code = normalize_invitation_code(raw_code)
    if not INVITATION_CODE_PATTERN.fullmatch(normalized_code):
        return None, "Authorization could not be verified."
    code_hash = invitation_code_hash(normalized_code)
    invitation = db.session.execute(
        db.select(Invitation).where(Invitation.code_hash == code_hash)
    ).scalar_one_or_none()
    if invitation is None or not hmac.compare_digest(invitation.code_hash, code_hash):
        return None, "Authorization could not be verified."
    if invitation.status != "Active":
        return None, "Authorization could not be verified."
    if invitation_is_expired(invitation):
        invitation.status = "Expired"
        db.session.commit()
        return None, "Authorization could not be verified."
    if invitation.reserved_callsign and invitation.reserved_callsign != callsign:
        return None, "This authorization is reserved for a different callsign."
    existing_user = db.session.execute(
        db.select(User.id).where(db.func.lower(User.username) == callsign.lower())
    ).scalar_one_or_none()
    if existing_user is not None:
        return None, "That callsign is unavailable."

    now = utc_now()
    user = User(
        username=callsign,
        password_hash=generate_password_hash(passphrase),
        has_seen_orientation=False,
    )
    try:
        db.session.add(user)
        db.session.flush()
        claimed = db.session.execute(
            db.update(Invitation)
            .where(
                Invitation.id == invitation.id,
                Invitation.status == "Active",
                db.or_(
                    Invitation.expires_at.is_(None),
                    Invitation.expires_at > now,
                ),
            )
            .values(
                status="Used",
                used_at=now,
                used_by_user_id=user.id,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.session.rollback()
            return None, "Authorization could not be verified."
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "That callsign is unavailable."
    except SQLAlchemyError:
        db.session.rollback()
        return None, "Authorization could not be completed. Try again."
    return user, None
