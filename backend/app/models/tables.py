from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024
ENGLISH_TSV = "to_tsvector('english', text)"


def fk(target: str, ondelete: str = "CASCADE", **kwargs) -> ForeignKey:
    return ForeignKey(target, ondelete=ondelete, **kwargs)


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "user"
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="student")


class Course(Base):
    __tablename__ = "course"
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="draft")


class Lesson(Base):
    __tablename__ = "lesson"
    course_id: Mapped[int] = mapped_column(fk("course.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    active_revision_id: Mapped[int | None] = mapped_column(
        fk("lesson_revision.id", "SET NULL", use_alter=True, name="fk_lesson_active_revision")
    )
    status: Mapped[str] = mapped_column(String, default="draft")


class Upload(Base):
    __tablename__ = "upload"
    lesson_id: Mapped[int] = mapped_column(fk("lesson.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String)
    s3_upload_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="uploading")


class TranscriptAsset(Base):
    __tablename__ = "transcript_asset"
    lesson_id: Mapped[int] = mapped_column(fk("lesson.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)


class VideoAsset(Base):
    """A new uploaded transcript gets its own copy of this row, so the live lines stay put."""

    __tablename__ = "video_asset"
    lesson_id: Mapped[int] = mapped_column(fk("lesson.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String)
    transcript_asset_id: Mapped[int | None] = mapped_column(fk("transcript_asset.id", "SET NULL"))
    hls_key: Mapped[str | None] = mapped_column(String)
    audio_key: Mapped[str | None] = mapped_column(String)
    shots_key: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="uploaded")


class DeckAsset(Base):
    __tablename__ = "deck_asset"
    lesson_id: Mapped[int] = mapped_column(fk("lesson.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    slide_count: Mapped[int | None] = mapped_column(Integer)
    ocr_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="uploaded")


class LessonRevision(Base):
    __tablename__ = "lesson_revision"
    lesson_id: Mapped[int] = mapped_column(fk("lesson.id"), index=True)
    video_asset_id: Mapped[int] = mapped_column(fk("video_asset.id"))
    deck_asset_id: Mapped[int | None] = mapped_column(fk("deck_asset.id"))
    status: Mapped[str] = mapped_column(String, default="processing")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segment"
    __table_args__ = (UniqueConstraint("video_asset_id", "seq"),)
    video_asset_id: Mapped[int] = mapped_column(fk("video_asset.id"))
    seq: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_corrected: Mapped[str | None] = mapped_column(Text)
    admin_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def display_text(self) -> str:
        return self.text_corrected or self.text


class Slide(Base):
    __tablename__ = "slide"
    __table_args__ = (UniqueConstraint("deck_asset_id", "number"),)
    deck_asset_id: Mapped[int] = mapped_column(fk("deck_asset.id"))
    number: Mapped[int] = mapped_column(Integer)
    image_key: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class SlideInterval(Base):
    """slide_id NULL is the OFF state: the professor is not on a slide."""

    __tablename__ = "slide_interval"
    revision_id: Mapped[int] = mapped_column(fk("lesson_revision.id"), index=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    slide_id: Mapped[int | None] = mapped_column(fk("slide.id"))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    method: Mapped[str] = mapped_column(String, default="visual")
    source: Mapped[str] = mapped_column(String, default="auto")


class Passage(Base):
    __tablename__ = "passage"
    __table_args__ = (
        Index("ix_passage_course_revision", "course_id", "revision_id"),
        Index("ix_passage_tsv", "tsv", postgresql_using="gin"),
    )
    revision_id: Mapped[int] = mapped_column(fk("lesson_revision.id"))
    course_id: Mapped[int] = mapped_column(fk("course.id"))
    first_seq: Mapped[int] = mapped_column(Integer)
    last_seq: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    slide_id: Mapped[int | None] = mapped_column(fk("slide.id", "SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    tsv = mapped_column(TSVECTOR, Computed(ENGLISH_TSV, persisted=True))


class ExtractionUnit(Base):
    """Verified GLM output per teaching unit, so an outage resumes instead of restarting."""

    __tablename__ = "extraction_unit"
    __table_args__ = (UniqueConstraint("revision_id", "unit_index"),)
    revision_id: Mapped[int] = mapped_column(fk("lesson_revision.id"))
    unit_index: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JSONB)


class Concept(Base):
    __tablename__ = "concept"
    __table_args__ = (UniqueConstraint("course_id", "name"),)
    course_id: Mapped[int] = mapped_column(fk("course.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    embedding = mapped_column(Vector(EMBEDDING_DIM))


class Statement(Base):
    __tablename__ = "statement"
    __table_args__ = (
        Index("ix_statement_course_revision", "course_id", "revision_id"),
        Index("ix_statement_tsv", "tsv", postgresql_using="gin"),
    )
    revision_id: Mapped[int] = mapped_column(fk("lesson_revision.id"))
    course_id: Mapped[int] = mapped_column(fk("course.id"))
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    tsv = mapped_column(TSVECTOR, Computed(ENGLISH_TSV, persisted=True))


class StatementEvidence(Base):
    __tablename__ = "statement_evidence"
    statement_id: Mapped[int] = mapped_column(fk("statement.id"), index=True)
    passage_id: Mapped[int] = mapped_column(fk("passage.id"), index=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)


class StatementConcept(Base):
    __tablename__ = "statement_concept"
    __table_args__ = (UniqueConstraint("statement_id", "concept_id"),)
    statement_id: Mapped[int] = mapped_column(fk("statement.id"), index=True)
    concept_id: Mapped[int] = mapped_column(fk("concept.id"), index=True)


class ConceptEdge(Base):
    __tablename__ = "concept_edge"
    __table_args__ = (UniqueConstraint("course_id", "source_id", "target_id", "type"),)
    course_id: Mapped[int] = mapped_column(fk("course.id"), index=True)
    source_id: Mapped[int] = mapped_column(fk("concept.id"), index=True)
    target_id: Mapped[int] = mapped_column(fk("concept.id"), index=True)
    type: Mapped[str] = mapped_column(String)


class EdgeEvidence(Base):
    __tablename__ = "edge_evidence"
    __table_args__ = (UniqueConstraint("edge_id", "statement_id"),)
    edge_id: Mapped[int] = mapped_column(fk("concept_edge.id"), index=True)
    statement_id: Mapped[int] = mapped_column(fk("statement.id"), index=True)


class PipelineStage(Base):
    __tablename__ = "pipeline_stage"
    __table_args__ = (UniqueConstraint("revision_id", "name"),)
    revision_id: Mapped[int] = mapped_column(fk("lesson_revision.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatSession(Base):
    __tablename__ = "chat_session"
    user_id: Mapped[int] = mapped_column(fk("user.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(fk("lesson.id"), index=True)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    session_id: Mapped[int] = mapped_column(fk("chat_session.id"), index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    grounding: Mapped[str | None] = mapped_column(String)
    citations: Mapped[list | None] = mapped_column(JSONB)


class LLMUsage(Base):
    __tablename__ = "llm_usage"
    purpose: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    lesson_id: Mapped[int | None] = mapped_column(fk("lesson.id", "SET NULL"))
    user_id: Mapped[int | None] = mapped_column(fk("user.id", "SET NULL"))
