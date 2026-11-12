from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models import User

COOKIE = "session"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_token(user_id: int) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(hours=settings.jwt_ttl_hours)
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.jwt_secret, "HS256")


def read_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        return int(jwt.decode(token, get_settings().jwt_secret, ["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


async def current_user(
    session_cookie: str | None = Cookie(None, alias=COOKIE),
    db: AsyncSession = Depends(get_session),
) -> User:
    user_id = read_token(session_cookie)
    user = await db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user
