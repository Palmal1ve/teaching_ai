"""Plain `def` routes: the GLM client is synchronous, so FastAPI runs these in a thread."""
from datetime import UTC, datetime

import redis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.answer import answer_question
from app.core.config import get_settings
from app.core.db import get_sync_session
from app.core.embeddings import EmbedderUnavailable
from app.core.llm import LLMUnavailable, get_llm
from app.core.security import current_user
from app.models import ChatMessage, ChatSession, Course, Lesson, LessonRevision, User
from app.schemas.api import AnswerOut, Ask, ChatSessionIn, ChatSessionOut, MessageOut

router = APIRouter(tags=["chat"])


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url)


def _check_lesson(db: Session, lesson_id: int, user: User, revision_id: int | None) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    if user.role == "admin":
        return lesson
    course = db.get(Course, lesson.course_id)
    if course.status != "published" or lesson.active_revision_id is None or revision_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
    return lesson


def _own_session(db: Session, session_id: int, user: User) -> ChatSession:
    chat = db.get(ChatSession, session_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")
    return chat


@router.post("/lessons/{lesson_id}/chat/sessions", response_model=ChatSessionOut)
def start_chat(
    lesson_id: int,
    body: ChatSessionIn | None = None,
    db: Session = Depends(get_sync_session),
    user: User = Depends(current_user),
):
    _check_lesson(db, lesson_id, user, body.revision_id if body else None)
    chat = ChatSession(user_id=user.id, lesson_id=lesson_id)
    db.add(chat)
    db.commit()
    return ChatSessionOut(id=chat.id)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
def history(
    session_id: int,
    db: Session = Depends(get_sync_session),
    user: User = Depends(current_user),
):
    _own_session(db, session_id, user)
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)
    )
    return [
        MessageOut(
            id=m.id, role=m.role, text=m.content, citations=m.citations or [], grounding=m.grounding
        )
        for m in rows
    ]


def _take_quota(store: redis.Redis, user: User) -> str | None:
    if user.role == "admin":
        return None
    key = f"questions:{user.id}:{datetime.now(UTC):%Y%m%d}"
    count = store.incr(key)
    store.expire(key, 2 * 24 * 3600)
    if count > get_settings().questions_per_day:
        store.decr(key)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Daily question limit reached")
    return key


@router.post("/chat/sessions/{session_id}/messages", response_model=AnswerOut)
def ask(
    session_id: int,
    body: Ask,
    db: Session = Depends(get_sync_session),
    user: User = Depends(current_user),
    llm=Depends(get_llm),
    store: redis.Redis = Depends(get_redis),
):
    chat = _own_session(db, session_id, user)
    lesson = _check_lesson(db, chat.lesson_id, user, body.revision_id)
    preview = None
    if body.revision_id is not None:
        preview = db.get(LessonRevision, body.revision_id)
        if preview is None or preview.lesson_id != lesson.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")

    quota_key = _take_quota(store, user)
    try:
        answer = answer_question(
            db, llm, lesson, chat.id, user.id, body.text, body.current_time_ms, preview
        )
    except (LLMUnavailable, EmbedderUnavailable):
        db.rollback()
        if quota_key:
            store.decr(quota_key)
        return JSONResponse({"code": "assistant_offline"}, status.HTTP_503_SERVICE_UNAVAILABLE)
    db.commit()
    message_id = db.scalar(
        select(ChatMessage.id)
        .where(ChatMessage.session_id == chat.id)
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    return AnswerOut(
        message_id=message_id,
        text=answer.text,
        citations=answer.citations,
        grounding=answer.grounding,
    )
