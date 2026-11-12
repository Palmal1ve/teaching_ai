import hashlib
import os
import re

os.environ.update(
    DATABASE_URL="postgresql+psycopg://new@localhost/course_test",
    JWT_SECRET="test-secret-long-enough-for-hs256-signing",
    LLM_BASE_URL="http://127.0.0.1:1/v1",
    REDIS_URL="redis://127.0.0.1:1/0",
)

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.api.chat import get_redis  # noqa: E402
from app.core import db as db_module  # noqa: E402
from app.core import embeddings  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import session_scope  # noqa: E402
from app.core.llm import LLMCall, LLMUnavailable, get_llm  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Course,
    DeckAsset,
    Lesson,
    LessonRevision,
    Passage,
    Slide,
    SlideInterval,
    Statement,
    StatementEvidence,
    TranscriptSegment,
    User,
    VideoAsset,
)


def fake_vector(text_: str) -> list[float]:
    """Bag of words hashed into 1024 dimensions: shared words mean a high cosine."""
    vector = np.zeros(embeddings.DIMENSIONS)
    for word in re.findall(r"[a-z0-9]+", text_.lower()):
        digest = hashlib.md5(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "little") % embeddings.DIMENSIONS] += 1.0
    norm = np.linalg.norm(vector)
    return (vector / norm if norm else vector).tolist()


class _Response:
    def __init__(self, texts):
        self.texts = texts

    def raise_for_status(self):
        pass

    def json(self):
        return {"vectors": [fake_vector(t) for t in self.texts]}


class FakeEmbedder:
    def post(self, path, json):
        return _Response(json["texts"])


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.down = False
        self.reply = "No material."
        self.structured = []
        self.messages = None

    def chat(self, messages, max_tokens=512, schema=None, calls=None):
        if self.down:
            raise LLMUnavailable("ConnectError")
        self.messages = messages
        if calls is not None:
            calls.append(LLMCall(10, 5, 1))
        return self.reply

    def complete_json(self, system, user, schema, max_tokens=512, calls=None):
        if self.down:
            raise LLMUnavailable("ConnectError")
        if calls is not None:
            calls.append(LLMCall(10, 5, 1))
        return self.structured.pop(0) if self.structured else None


class FakeRedis:
    def __init__(self):
        self.values = {}

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def decr(self, key):
        self.values[key] -= 1

    def expire(self, key, seconds):
        pass


@pytest.fixture(scope="session", autouse=True)
def schema():
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with session_scope() as session:
        session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    monkeypatch.setattr(embeddings, "_client", lambda: FakeEmbedder())
    db_module._async_factory.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    monkeypatch.setattr("app.pipeline.stages.resolve_concepts.get_llm", lambda: fake)
    monkeypatch.setattr("app.pipeline.stages.extract_knowledge.get_llm", lambda: fake)
    yield fake
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def client(llm):
    fake_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_redis, None)


@pytest.fixture
def enqueued(monkeypatch):
    calls = []
    monkeypatch.setattr("app.pipeline.runner.enqueue", lambda sid, name: calls.append(name))
    return calls


def make_user(email="student@x.edu", role="student", password="pw"):
    with session_scope() as session:
        user = User(email=email, password_hash=hash_password(password), role=role)
        session.add(user)
    return user


def login(client, email="student@x.edu", password="pw"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def make_lesson(session, course_id=None, position=1, title="Shortest paths", published=True):
    if course_id is None:
        course = Course(title="Algorithms", status="published" if published else "draft")
        session.add(course)
        session.flush()
        course_id = course.id
    lesson = Lesson(course_id=course_id, position=position, title=title)
    session.add(lesson)
    session.flush()
    return lesson


def make_revision(session, lesson, with_deck=True, active=True, status="published"):
    video = VideoAsset(
        lesson_id=lesson.id,
        storage_key=f"uploads/{lesson.id}/v.mp4",
        hls_key=f"videos/{lesson.id}/hls/master.m3u8",
        duration_ms=600_000,
    )
    session.add(video)
    session.flush()
    deck = None
    if with_deck:
        deck = DeckAsset(
            lesson_id=lesson.id, storage_key="d", filename="d.pptx", slide_count=2
        )
        session.add(deck)
        session.flush()
    revision = LessonRevision(
        lesson_id=lesson.id,
        video_asset_id=video.id,
        deck_asset_id=deck.id if deck else None,
        status=status,
    )
    session.add(revision)
    session.flush()
    if active:
        lesson.active_revision_id = revision.id
    return revision


def add_passage(session, revision, course_id, text_, start_ms=0, end_ms=30_000, slide_id=None):
    passage = Passage(
        revision_id=revision.id,
        course_id=course_id,
        first_seq=0,
        last_seq=0,
        start_ms=start_ms,
        end_ms=end_ms,
        slide_id=slide_id,
        text=text_,
        embedding=fake_vector(text_),
    )
    session.add(passage)
    session.flush()
    return passage


def add_statement(session, revision, course_id, passage, text_, kind="explanation"):
    statement = Statement(
        revision_id=revision.id,
        course_id=course_id,
        kind=kind,
        text=text_,
        embedding=fake_vector(text_),
    )
    session.add(statement)
    session.flush()
    session.add(
        StatementEvidence(
            statement_id=statement.id,
            passage_id=passage.id,
            start_ms=passage.start_ms,
            end_ms=passage.end_ms,
            quote=text_[:40],
        )
    )
    session.flush()
    return statement


def add_slide_timeline(session, revision):
    slides = []
    for number, body in ((1, "Edge relaxation"), (2, "Greedy choice")):
        slide = Slide(
            deck_asset_id=revision.deck_asset_id,
            number=number,
            image_key=f"decks/{revision.deck_asset_id}/slides/{number:04d}.png",
            text=body,
        )
        session.add(slide)
        session.flush()
        slides.append(slide)
    session.add_all(
        [
            SlideInterval(
                revision_id=revision.id, start_ms=0, end_ms=300_000, slide_id=slides[0].id
            ),
            SlideInterval(
                revision_id=revision.id,
                start_ms=300_000,
                end_ms=600_000,
                slide_id=slides[1].id,
                method="speech",
            ),
        ]
    )
    session.add(
        TranscriptSegment(
            video_asset_id=revision.video_asset_id,
            seq=0,
            start_ms=1000,
            end_ms=5000,
            text="So we relax the edges here",
        )
    )
    session.flush()
    return slides
