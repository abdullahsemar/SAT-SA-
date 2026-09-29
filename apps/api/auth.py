import datetime
import hashlib
import hmac
import json
import secrets
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from apps.api.config import settings
from db.models.access import SessionRecord, User
from db.session import get_db

ph = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(f"{token}:{settings.session_secret}".encode("utf-8")).hexdigest()


def create_user_session(user: User, db: Session) -> tuple[str, str, datetime.datetime]:
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)
    csrf_token = secrets.token_hex(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=settings.session_max_age_seconds
    )

    sess = SessionRecord(
        id=token_hash,
        user_id=user.id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    db.add(sess)
    db.commit()
    return token, csrf_token, expires_at


def set_session_cookie(response: Response, token: str, expires_at: datetime.datetime):
    response.set_cookie(
        key="sat_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # Offline loopback dev
        expires=expires_at,
        path="/",
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(key="sat_session", path="/")


def get_current_user_and_session(
    request: Request,
    sat_session: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_db),
) -> tuple[User, SessionRecord]:
    # Also support Authorization Bearer or X-Session-Token header for programmatic API testing
    token = sat_session
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif request.headers.get("X-Session-Token"):
            token = request.headers.get("X-Session-Token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication session required",
        )

    token_hash = hash_session_token(token)
    sess = db.get(SessionRecord, token_hash)
    if not sess:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    if sess.expires_at.tzinfo is None:
        sess_expires = sess.expires_at.replace(tzinfo=datetime.timezone.utc)
    else:
        sess_expires = sess.expires_at

    if sess_expires < now:
        db.delete(sess)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired",
        )

    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or deleted",
        )

    # CSRF Check on state-modifying HTTP methods if session came from cookie
    if sat_session and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_header or not hmac.compare_digest(csrf_header, sess.csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed",
            )

    return user, sess


def get_current_user(
    auth_tuple: tuple[User, SessionRecord] = Depends(get_current_user_and_session),
) -> User:
    return auth_tuple[0]


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required",
        )
    return user


def permitted_entity_ids(user: User) -> list[str] | None:
    """None means unrestricted; an empty list always means no entity access."""
    if user.role == "admin":
        return None
    try:
        allowed = json.loads(user.entity_scope)
    except (TypeError, ValueError):
        return []
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        return []
    return None if "*" in allowed else allowed


def check_entity_access(user: User, entity_id: str) -> None:
    allowed = permitted_entity_ids(user)
    if allowed is not None and entity_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to entity '{entity_id}'",
        )
