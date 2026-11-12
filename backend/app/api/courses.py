from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import current_user
from app.models import (
    Concept,
    ConceptEdge,
    Course,
    EdgeEvidence,
    Lesson,
    LessonRevision,
    Statement,
    StatementConcept,
    StatementEvidence,
    User,
    VideoAsset,
)
from app.schemas.api import (
    CourseLessonOut,
    CourseOut,
    CourseOverview,
    GraphEdge,
    GraphMoment,
    GraphNode,
    GraphOut,
    LessonOut,
)

router = APIRouter(prefix="/courses", tags=["courses"], dependencies=[Depends(current_user)])


async def visible_course(db: AsyncSession, course_id: int, user: User) -> Course:
    course = await db.get(Course, course_id)
    if course is None or (course.status != "published" and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


@router.get("", response_model=list[CourseOut])
async def list_courses(db: AsyncSession = Depends(get_session)):
    rows = await db.scalars(
        select(Course).where(Course.status == "published").order_by(Course.title)
    )
    return rows.all()


@router.get("/{course_id}", response_model=CourseOverview)
async def get_course(
    course_id: int,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    course = await visible_course(db, course_id, user)
    lessons = (
        await db.scalars(
            select(Lesson)
            .where(Lesson.course_id == course_id, Lesson.active_revision_id.is_not(None))
            .order_by(Lesson.position)
        )
    ).all()
    revisions = [lesson.active_revision_id for lesson in lessons]
    durations = dict(
        (
            await db.execute(
                select(LessonRevision.id, VideoAsset.duration_ms)
                .join(VideoAsset, VideoAsset.id == LessonRevision.video_asset_id)
                .where(LessonRevision.id.in_(revisions))
            )
        ).all()
    )
    concepts = dict(
        (
            await db.execute(
                select(Statement.revision_id, func.count(StatementConcept.concept_id.distinct()))
                .join(StatementConcept, StatementConcept.statement_id == Statement.id)
                .where(Statement.revision_id.in_(revisions))
                .group_by(Statement.revision_id)
            )
        ).all()
    )
    return CourseOverview(
        **CourseOut.model_validate(course).model_dump(),
        lessons=[
            CourseLessonOut(
                **LessonOut.model_validate(lesson).model_dump(),
                duration_ms=durations.get(lesson.active_revision_id) or 0,
                concept_count=concepts.get(lesson.active_revision_id, 0),
            )
            for lesson in lessons
        ],
    )


@router.get("/{course_id}/graph", response_model=GraphOut)
async def course_graph(
    course_id: int,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(current_user),
):
    """Concepts and edges backed by a published lesson, with the moments each was taught."""
    course = await visible_course(db, course_id, user)
    lessons = {
        lesson.active_revision_id: lesson
        for lesson in await db.scalars(
            select(Lesson).where(
                Lesson.course_id == course_id, Lesson.active_revision_id.is_not(None)
            )
        )
    }
    rows = await db.execute(
        select(
            StatementConcept.concept_id,
            Statement.revision_id,
            Statement.text,
            func.min(StatementEvidence.start_ms),
        )
        .join(Statement, Statement.id == StatementConcept.statement_id)
        .join(StatementEvidence, StatementEvidence.statement_id == Statement.id)
        .where(Statement.course_id == course_id, Statement.revision_id.in_(lessons))
        .group_by(StatementConcept.concept_id, Statement.id)
    )
    moments: dict[int, list[GraphMoment]] = {}
    for concept_id, revision_id, text, start_ms in rows:
        lesson = lessons[revision_id]
        moments.setdefault(concept_id, []).append(
            GraphMoment(
                lesson_id=lesson.id,
                lesson_title=lesson.title,
                lesson_position=lesson.position,
                start_ms=start_ms,
                text=text,
            )
        )
    concepts = await db.scalars(
        select(Concept).where(Concept.id.in_(moments)).order_by(Concept.name)
    )
    supported_edges = (
        select(EdgeEvidence.edge_id)
        .join(Statement, Statement.id == EdgeEvidence.statement_id)
        .where(Statement.course_id == course_id, Statement.revision_id.in_(lessons))
    )
    edges = await db.scalars(
        select(ConceptEdge)
        .where(
            ConceptEdge.course_id == course_id,
            ConceptEdge.id.in_(supported_edges),
            ConceptEdge.source_id.in_(moments),
            ConceptEdge.target_id.in_(moments),
        )
        .order_by(ConceptEdge.id)
    )
    return GraphOut(
        course_id=course.id,
        course_title=course.title,
        nodes=[
            GraphNode(
                id=c.id,
                name=c.name,
                aliases=c.aliases,
                summary=c.summary,
                moments=sorted(
                    moments[c.id], key=lambda m: (m.lesson_position, m.start_ms)
                ),
            )
            for c in concepts
        ],
        edges=[GraphEdge(source=e.source_id, target=e.target_id, type=e.type) for e in edges],
    )
