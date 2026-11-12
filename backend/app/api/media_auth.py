"""nginx asks this route before serving any media path, and caches the answer for 60 seconds."""
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import COOKIE, read_token
from app.models import Course, Lesson, LessonRevision, User, VideoAsset

router = APIRouter(prefix="/internal", include_in_schema=False)

_PATH = re.compile(r"^/media/(?:(videos)/(\d+)/(hls|shots)/|(decks)/(\d+)/slides/)")


async def _published(db: AsyncSession, column, asset_id: int) -> bool:
    row = await db.scalar(
        select(Lesson.id)
        .join(LessonRevision, LessonRevision.id == Lesson.active_revision_id)
        .join(VideoAsset, VideoAsset.id == LessonRevision.video_asset_id)
        .join(Course, Course.id == Lesson.course_id)
        .where(column == asset_id, Course.status == "published")
        .limit(1)
    )
    return row is not None


@router.get("/media-auth")
async def media_auth(
    request: Request,
    original_uri: str = Header("", alias="X-Original-URI"),
    db: AsyncSession = Depends(get_session),
):
    match = _PATH.match(original_uri)
    user_id = read_token(request.cookies.get(COOKIE))
    user = await db.get(User, user_id) if user_id else None
    if match is None or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    if user.role == "admin":
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    videos, video_id, area, decks, deck_id = match.groups()
    if videos and area == "hls":
        # A video copied for a new transcript streams the original's files.
        hls_key = await db.scalar(select(VideoAsset.hls_key).where(VideoAsset.id == int(video_id)))
        allowed = hls_key is not None and await _published(db, VideoAsset.hls_key, hls_key)
    elif decks:
        allowed = await _published(db, LessonRevision.deck_asset_id, int(deck_id))
    else:
        allowed = False
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
