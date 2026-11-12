from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import current_user
from app.models import (
    Course,
    Lesson,
    LessonRevision,
    Slide,
    SlideInterval,
    TranscriptSegment,
    User,
    VideoAsset,
)
from app.schemas.api import IntervalOut, PlayerOut, SegmentOut, SlideOut

router = APIRouter(prefix="/lessons", tags=["lessons"])


def media_url(key: str) -> str:
    return f"/media/{key}"


async def slides_for(db: AsyncSession, deck_id: int | None) -> list[Slide]:
    if deck_id is None:
        return []
    rows = await db.scalars(
        select(Slide).where(Slide.deck_asset_id == deck_id).order_by(Slide.number)
    )
    return list(rows)


def slide_out(slide: Slide) -> SlideOut:
    return SlideOut(
        id=slide.id,
        number=slide.number,
        image_url=media_url(slide.image_key),
        hidden=slide.hidden,
    )


async def viewable_revision(
    db: AsyncSession, lesson: Lesson, user: User, revision_id: int | None
) -> LessonRevision:
    """Students get the active revision. Admins may name a draft, to review it as a student."""
    course = await db.get(Course, lesson.course_id)
    if user.role == "admin" and revision_id is not None:
        revision = await db.get(LessonRevision, revision_id)
        if revision is None or revision.lesson_id != lesson.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
        return revision
    visible = user.role == "admin" or course.status == "published"
    if not visible or lesson.active_revision_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return await db.get(LessonRevision, lesson.active_revision_id)


@router.get("/{lesson_id}/player", response_model=PlayerOut)
async def player(
    lesson_id: int,
    revision_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    lesson = await db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    revision = await viewable_revision(db, lesson, user, revision_id)
    course = await db.get(Course, lesson.course_id)
    video = await db.get(VideoAsset, revision.video_asset_id)
    slides = await slides_for(db, revision.deck_asset_id)
    numbers = {slide.id: slide.number for slide in slides}

    segments = await db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.video_asset_id == video.id)
        .order_by(TranscriptSegment.seq)
    )
    intervals = await db.scalars(
        select(SlideInterval)
        .where(SlideInterval.revision_id == revision.id)
        .order_by(SlideInterval.start_ms)
    )
    return PlayerOut(
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        course_id=course.id,
        course_title=course.title,
        revision_id=revision.id,
        hls_url=media_url(video.hls_key) if video.hls_key else None,
        duration_ms=video.duration_ms or 0,
        transcript=[
            SegmentOut(
                id=s.id, seq=s.seq, start_ms=s.start_ms, end_ms=s.end_ms, text=s.display_text
            )
            for s in segments
        ],
        slides=[slide_out(s) for s in slides],
        timeline=[
            IntervalOut(
                start_ms=i.start_ms,
                end_ms=i.end_ms,
                slide=numbers.get(i.slide_id),
                estimated=i.method == "speech" and i.source == "auto",
            )
            for i in intervals
        ],
    )
