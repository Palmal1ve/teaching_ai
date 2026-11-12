import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import COOKIE, create_token, current_user, hash_password, verify_password
from app.models import User
from app.schemas.api import Login, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def sign_in(response: Response, user: User) -> User:
    response.set_cookie(
        COOKIE,
        create_token(user.id),
        httponly=True,
        samesite="lax",
        max_age=get_settings().jwt_ttl_hours * 3600,
    )
    return user


@router.post("/login", response_model=UserOut)
async def login(body: Login, response: Response, db: AsyncSession = Depends(get_session)):
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    return sign_in(response, user)


@router.get("/demo")
async def demo_enabled():
    return {"enabled": get_settings().demo_login}


@router.post("/demo/{role}", response_model=UserOut)
async def demo_login(
    role: Literal["student", "admin"], response: Response, db: AsyncSession = Depends(get_session)
):
    """One-click accounts for demos. Off unless DEMO_LOGIN is set; their password is never known."""
    if not get_settings().demo_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    email = f"demo.{role}@example.edu"
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, password_hash=hash_password(secrets.token_urlsafe(32)), role=role)
        db.add(user)
        await db.commit()
    return sign_in(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(COOKIE)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user
