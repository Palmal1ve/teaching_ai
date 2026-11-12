from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Login(BaseModel):
    email: EmailStr
    password: str


class UserOut(Orm):
    id: int
    email: str
    role: str


class CourseIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""


class CoursePatch(BaseModel):
    title: str | None = Field(None, min_length=1)
    description: str | None = None
    status: Literal["draft", "published"] | None = None


class CourseOut(Orm):
    id: int
    title: str
    description: str
    status: str


class LessonIn(BaseModel):
    course_id: int
    title: str = Field(min_length=1)
    position: int | None = None


class LessonPatch(BaseModel):
    title: str | None = Field(None, min_length=1)
    position: int | None = None


class LessonOut(Orm):
    id: int
    course_id: int
    position: int
    title: str
    status: str
    active_revision_id: int | None


class CourseDetail(CourseOut):
    lessons: list[LessonOut]


class CourseLessonOut(LessonOut):
    duration_ms: int
    concept_count: int


class CourseOverview(CourseOut):
    lessons: list[CourseLessonOut]


class GraphMoment(BaseModel):
    lesson_id: int
    lesson_title: str
    lesson_position: int
    start_ms: int
    text: str


class GraphNode(BaseModel):
    id: int
    name: str
    aliases: list[str]
    summary: str
    moments: list[GraphMoment]


class GraphEdge(BaseModel):
    source: int
    target: int
    type: str


class GraphOut(BaseModel):
    course_id: int
    course_title: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class SegmentOut(BaseModel):
    id: int
    seq: int
    start_ms: int
    end_ms: int
    text: str


class SlideOut(BaseModel):
    id: int
    number: int
    image_url: str
    hidden: bool


class IntervalOut(BaseModel):
    start_ms: int
    end_ms: int
    slide: int | None
    estimated: bool


class PlayerOut(BaseModel):
    lesson_id: int
    lesson_title: str
    course_id: int
    course_title: str
    revision_id: int
    hls_url: str | None
    duration_ms: int
    transcript: list[SegmentOut]
    slides: list[SlideOut]
    timeline: list[IntervalOut]


class ChatSessionIn(BaseModel):
    revision_id: int | None = None


class ChatSessionOut(BaseModel):
    id: int


class Ask(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    current_time_ms: int = Field(ge=0)
    revision_id: int | None = None


class Citation(BaseModel):
    n: int
    lesson_id: int
    start_ms: int
    label: str
    slide: int | None
    quote: str


class AnswerOut(BaseModel):
    message_id: int
    text: str
    citations: list[Citation]
    grounding: Literal["grounded", "partial", "not_covered"]


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    citations: list[Citation]
    grounding: str | None


class UploadIn(BaseModel):
    kind: Literal["video", "deck", "transcript"]
    filename: str = Field(min_length=1)
    size: int = Field(gt=0)


class UploadPart(BaseModel):
    part_number: int
    url: str


class UploadOut(BaseModel):
    upload_id: int
    part_size: int
    parts: list[UploadPart]


class DonePart(BaseModel):
    part_number: int
    size: int
    etag: str


class UploadStatus(UploadOut):
    done: list[DonePart]


class CompleteOut(BaseModel):
    revision_id: int | None


class StageOut(Orm):
    name: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RevisionOut(BaseModel):
    id: int
    status: str
    has_deck: bool
    transcript_file: str | None
    active: bool
    stages: list[StageOut]


class UnsavedFile(BaseModel):
    kind: Literal["video", "deck", "transcript"]
    filename: str


class LessonAdminOut(LessonOut):
    revisions: list[RevisionOut]
    unsaved: list[UnsavedFile]


class TimelineRow(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int
    slide: int | None
    confidence: float = 1.0
    method: Literal["visual", "speech"] = "visual"
    source: Literal["auto", "manual"] = "auto"


class TimelineOut(BaseModel):
    duration_ms: int
    rows: list[TimelineRow]
    slides: list[SlideOut]


class TimelineIn(BaseModel):
    rows: list[TimelineRow]


class SegmentPatch(BaseModel):
    text: str = Field(min_length=1)
