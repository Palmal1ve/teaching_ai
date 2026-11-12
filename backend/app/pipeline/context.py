from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Lesson, LessonRevision


@dataclass(frozen=True)
class StageContext:
    revision_id: int
    lesson_id: int
    course_id: int
    video_id: int
    deck_id: int | None


def load_context(session: Session, revision_id: int) -> StageContext:
    revision = session.get(LessonRevision, revision_id)
    lesson = session.get(Lesson, revision.lesson_id)
    return StageContext(
        revision_id=revision.id,
        lesson_id=lesson.id,
        course_id=lesson.course_id,
        video_id=revision.video_asset_id,
        deck_id=revision.deck_asset_id,
    )
