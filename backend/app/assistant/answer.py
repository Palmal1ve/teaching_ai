"""One retrieval and one GLM call per question, then citation checking."""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.citations import CheckedAnswer, check
from app.assistant.prompt import build_messages
from app.assistant.retrieval import retrieve, visible_revisions
from app.core.config import get_settings
from app.core.embeddings import embed
from app.core.llm import LLMCall, usage_rows
from app.models import ChatMessage, Lesson, LessonRevision

HISTORY_MESSAGES = 6
_MARK = re.compile(r"\s+\[(\d+)\]")


def _history(session: Session, session_id: int) -> list[ChatMessage]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(HISTORY_MESSAGES)
    ).all()
    return list(reversed(rows))


def without_marks(message: ChatMessage) -> str:
    numbers = {citation["n"] for citation in message.citations or []}
    return _MARK.sub(
        lambda mark: "" if int(mark[1]) in numbers else mark[0], message.content
    )


def answer_question(
    session: Session,
    llm,
    lesson: Lesson,
    session_id: int,
    user_id: int,
    question: str,
    current_ms: int,
    preview: LessonRevision | None = None,
) -> CheckedAnswer:
    settings = get_settings()
    earlier = _history(session, session_id)
    last_user = next((m.content for m in reversed(earlier) if m.role == "user"), "")
    search_text = f"{last_user}\n{question}".strip()

    vector = embed([search_text])[0]
    revisions = visible_revisions(session, lesson.course_id, preview)
    sources = retrieve(
        session, lesson.course_id, lesson, revisions, search_text, vector, current_ms
    )

    history = [{"role": m.role, "content": without_marks(m)} for m in earlier]
    messages = build_messages(sources, history, question)
    calls: list[LLMCall] = []
    reply = llm.chat(messages, max_tokens=settings.answer_max_tokens, calls=calls)

    checked = check(reply, sources, embed, settings.citation_min_similarity)
    session.add_all(
        [
            ChatMessage(session_id=session_id, role="user", content=question),
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content=checked.text,
                grounding=checked.grounding,
                citations=checked.citations,
            ),
            *usage_rows("chat", llm.model, calls, lesson.id, user_id),
        ]
    )
    return checked
