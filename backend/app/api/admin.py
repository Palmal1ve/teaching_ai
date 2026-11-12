import asyncio
import logging
from pathlib import Path

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.lessons import slide_out, slides_for
from app.core import storage
from app.core.config import get_settings
from app.core.db import get_session, get_sync_session, new_async_session
from app.core.security import require_admin
from app.models import (
    Course,
    DeckAsset,
    Lesson,
    LessonRevision,
    Passage,
    PipelineStage,
    SlideInterval,
    TranscriptAsset,
    TranscriptSegment,
    Upload,
    VideoAsset,
)
from app.pipeline.graph import STAGES
from app.pipeline.revisions import create_revision, latest_revision, sync_lesson_status
from app.pipeline.runner import advance, purge_storage, reembed_passages, retry_stage
from app.schemas.api import (
    CompleteOut,
    CourseDetail,
    CourseIn,
    CourseOut,
    CoursePatch,
    DonePart,
    LessonAdminOut,
    LessonIn,
    LessonOut,
    LessonPatch,
    RevisionOut,
    SegmentOut,
    SegmentPatch,
    StageOut,
    TimelineIn,
    TimelineOut,
    TimelineRow,
    UnsavedFile,
    UploadIn,
    UploadOut,
    UploadPart,
    UploadStatus,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
DECK_TYPES = {".pptx", ".ppt", ".pdf"}
TRANSCRIPT_TYPES = {".srt", ".vtt", ".pdf"}
FINAL_STATUSES = ("superseded", "published")


def _found[T](row: T | None, name: str) -> T:
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{name} not found")
    return row


# Courses


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(db: AsyncSession = Depends(get_session)):
    return (await db.scalars(select(Course).order_by(Course.id.desc()))).all()


@router.post("/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(body: CourseIn, db: AsyncSession = Depends(get_session)):
    course = Course(title=body.title, description=body.description)
    db.add(course)
    await db.commit()
    return course


@router.get("/courses/{course_id}", response_model=CourseDetail)
async def get_course(course_id: int, db: AsyncSession = Depends(get_session)):
    course = _found(await db.get(Course, course_id), "Course")
    lessons = await db.scalars(
        select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.position)
    )
    return CourseDetail(
        **CourseOut.model_validate(course).model_dump(),
        lessons=[LessonOut.model_validate(lesson) for lesson in lessons],
    )


@router.patch("/courses/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: int, body: CoursePatch, db: AsyncSession = Depends(get_session)
):
    course = _found(await db.get(Course, course_id), "Course")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.commit()
    return course


async def _storage_prefixes(db: AsyncSession, lesson_ids: list[int]) -> list[str]:
    videos = await db.scalars(select(VideoAsset.id).where(VideoAsset.lesson_id.in_(lesson_ids)))
    decks = await db.scalars(select(DeckAsset.id).where(DeckAsset.lesson_id.in_(lesson_ids)))
    return [f"videos/{i}/" for i in videos] + [f"decks/{i}/" for i in decks]


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: int, db: AsyncSession = Depends(get_session)):
    course = _found(await db.get(Course, course_id), "Course")
    lesson_ids = list(await db.scalars(select(Lesson.id).where(Lesson.course_id == course_id)))
    prefixes = await _storage_prefixes(db, lesson_ids)
    await db.delete(course)
    await db.commit()
    if prefixes:
        await run_in_threadpool(purge_storage.delay, prefixes)


# Lessons


@router.post("/lessons", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(body: LessonIn, db: AsyncSession = Depends(get_session)):
    _found(await db.get(Course, body.course_id), "Course")
    position = body.position
    if position is None:
        highest = await db.scalar(
            select(func.max(Lesson.position)).where(Lesson.course_id == body.course_id)
        )
        position = (highest or 0) + 1
    lesson = Lesson(course_id=body.course_id, title=body.title, position=position)
    db.add(lesson)
    await db.commit()
    return lesson


@router.get("/lessons/{lesson_id}", response_model=LessonAdminOut)
async def get_lesson(lesson_id: int, db: AsyncSession = Depends(get_session)):
    lesson = _found(await db.get(Lesson, lesson_id), "Lesson")
    revisions = await db.scalars(
        select(LessonRevision)
        .where(LessonRevision.lesson_id == lesson_id)
        .order_by(LessonRevision.id.desc())
    )
    result = []
    for revision in revisions:
        result.append(await _revision_out(db, revision, lesson))
    return LessonAdminOut(
        **LessonOut.model_validate(lesson).model_dump(),
        revisions=result,
        unsaved=await _unsaved(db, lesson_id),
    )


async def _unsaved(db: AsyncSession, lesson_id: int) -> list[UnsavedFile]:
    """The newest file of each kind that Save has not yet sent on."""
    files = []
    for model, kind, used_by in (
        (VideoAsset, "video", LessonRevision.video_asset_id),
        (DeckAsset, "deck", LessonRevision.deck_asset_id),
        (TranscriptAsset, "transcript", VideoAsset.transcript_asset_id),
    ):
        newest = await db.scalar(
            select(model).where(model.lesson_id == lesson_id).order_by(model.id.desc()).limit(1)
        )
        if newest is None or await db.scalar(select(used_by).where(used_by == newest.id).limit(1)):
            continue
        filename = await db.scalar(
            select(Upload.filename).where(Upload.storage_key == newest.storage_key)
        )
        files.append(UnsavedFile(kind=kind, filename=filename or ""))
    return files


async def _revision_out(
    db: AsyncSession, revision: LessonRevision, lesson: Lesson
) -> RevisionOut:
    stages = {
        s.name: s
        for s in await db.scalars(
            select(PipelineStage).where(PipelineStage.revision_id == revision.id)
        )
    }
    video = await db.get(VideoAsset, revision.video_asset_id)
    transcript = (
        await db.get(TranscriptAsset, video.transcript_asset_id)
        if video.transcript_asset_id
        else None
    )
    return RevisionOut(
        id=revision.id,
        status=revision.status,
        has_deck=revision.deck_asset_id is not None,
        transcript_file=transcript.filename if transcript else None,
        active=lesson.active_revision_id == revision.id,
        stages=[StageOut.model_validate(stages[n]) for n in STAGES if n in stages],
    )


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: int, body: LessonPatch, db: AsyncSession = Depends(get_session)
):
    lesson = _found(await db.get(Lesson, lesson_id), "Lesson")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(lesson, field, value)
    await db.commit()
    return lesson


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(lesson_id: int, db: AsyncSession = Depends(get_session)):
    lesson = _found(await db.get(Lesson, lesson_id), "Lesson")
    prefixes = await _storage_prefixes(db, [lesson_id])
    await db.delete(lesson)
    await db.commit()
    if prefixes:
        await run_in_threadpool(purge_storage.delay, prefixes)


# Uploads: plain `def` routes, because S3 and Celery calls block.


def _check_upload(body: UploadIn) -> str:
    settings = get_settings()
    suffix = Path(body.filename).suffix.lower()
    allowed, limit = {
        "video": (VIDEO_TYPES, settings.max_video_bytes),
        "deck": (DECK_TYPES, settings.max_deck_bytes),
        "transcript": (TRANSCRIPT_TYPES, settings.max_transcript_bytes),
    }[body.kind]
    if suffix not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{suffix or 'This file type'} is not supported"
        )
    if body.size > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File is too large")
    return suffix


def _part_urls(upload: Upload) -> list[UploadPart]:
    part_size = get_settings().upload_part_size
    count = max(1, -(-upload.size // part_size))
    return [
        UploadPart(
            part_number=n, url=storage.sign_part(upload.storage_key, upload.s3_upload_id, n)
        )
        for n in range(1, count + 1)
    ]


def _abort(upload: Upload) -> None:
    upload.status = "aborted"
    try:
        storage.client().abort_multipart_upload(
            Bucket=storage.bucket(), Key=upload.storage_key, UploadId=upload.s3_upload_id
        )
    except ClientError:
        log.warning("Upload %s was already gone from storage", upload.id)


def _abandon_earlier(db: Session, lesson_id: int, kind: str) -> None:
    """A tab closed mid-upload leaves a row behind, and it must not hold up the next attempt."""
    earlier = db.scalars(
        select(Upload).where(
            Upload.lesson_id == lesson_id, Upload.kind == kind, Upload.status == "uploading"
        )
    )
    for upload in earlier:
        _abort(upload)


@router.post("/lessons/{lesson_id}/uploads", response_model=UploadOut)
def start_upload(lesson_id: int, body: UploadIn, db: Session = Depends(get_sync_session)):
    _found(db.get(Lesson, lesson_id), "Lesson")
    suffix = _check_upload(body)
    _abandon_earlier(db, lesson_id, body.kind)
    upload = Upload(
        lesson_id=lesson_id,
        kind=body.kind,
        filename=body.filename,
        size=body.size,
        storage_key="",
        s3_upload_id="",
    )
    db.add(upload)
    db.flush()
    upload.storage_key = f"uploads/{upload.id}/source{suffix}"
    upload.s3_upload_id = storage.client().create_multipart_upload(
        Bucket=storage.bucket(), Key=upload.storage_key
    )["UploadId"]
    db.commit()
    return UploadOut(
        upload_id=upload.id,
        part_size=get_settings().upload_part_size,
        parts=_part_urls(upload),
    )


def _listed_parts(upload: Upload) -> list[dict]:
    parts: list[dict] = []
    marker = 0
    while True:
        page = storage.client().list_parts(
            Bucket=storage.bucket(),
            Key=upload.storage_key,
            UploadId=upload.s3_upload_id,
            PartNumberMarker=marker,
        )
        parts.extend(page.get("Parts", []))
        if not page.get("IsTruncated"):
            return parts
        marker = page["NextPartNumberMarker"]


@router.get("/uploads/{upload_id}", response_model=UploadStatus)
def upload_status(upload_id: int, db: Session = Depends(get_sync_session)):
    upload = _found(db.get(Upload, upload_id), "Upload")
    return UploadStatus(
        upload_id=upload.id,
        part_size=get_settings().upload_part_size,
        parts=_part_urls(upload),
        done=[
            DonePart(part_number=p["PartNumber"], size=p["Size"], etag=p["ETag"])
            for p in _listed_parts(upload)
        ],
    )


def _newest[T](db: Session, model: type[T], lesson_id: int) -> T | None:
    return db.scalars(
        select(model).where(model.lesson_id == lesson_id).order_by(model.id.desc()).limit(1)
    ).first()


def _with_transcript(db: Session, video: VideoAsset, lesson_id: int) -> VideoAsset:
    """A transcript no video uses yet belongs to the newest video.

    A video already in a revision is copied, keeping its streaming, audio and frames, so the
    lines the live version shows stay as they are until the new one is published.
    """
    transcript = _newest(db, TranscriptAsset, lesson_id)
    if transcript is None or db.scalar(
        select(VideoAsset.id).where(VideoAsset.transcript_asset_id == transcript.id).limit(1)
    ):
        return video
    in_revision = db.scalar(
        select(LessonRevision.id).where(LessonRevision.video_asset_id == video.id).limit(1)
    )
    if in_revision:
        video = VideoAsset(
            lesson_id=video.lesson_id,
            storage_key=video.storage_key,
            hls_key=video.hls_key,
            audio_key=video.audio_key,
            shots_key=video.shots_key,
            duration_ms=video.duration_ms,
            width=video.width,
            height=video.height,
            status=video.status,
        )
        db.add(video)
    video.transcript_asset_id = transcript.id
    db.flush()
    return video


def _start_pipeline(db: Session, lesson: Lesson) -> int | None:
    """Pairs the newest video, deck and transcript into a revision, unless nothing changed."""
    video = _newest(db, VideoAsset, lesson.id)
    if video is None:
        return None
    video = _with_transcript(db, video, lesson.id)
    deck = _newest(db, DeckAsset, lesson.id)
    deck_id = deck.id if deck else None
    latest = latest_revision(db, lesson.id)
    if latest and (latest.video_asset_id, latest.deck_asset_id) == (video.id, deck_id):
        return None
    return create_revision(db, lesson, video, deck).id


@router.post("/uploads/{upload_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_upload(upload_id: int, db: Session = Depends(get_sync_session)):
    upload = db.scalars(
        select(Upload).where(Upload.id == upload_id).with_for_update()
    ).first()
    _found(upload, "Upload")
    if upload.status != "uploading":
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload already finished")
    parts = _listed_parts(upload)
    if not parts:
        raise HTTPException(status.HTTP_409_CONFLICT, "No parts were uploaded")
    storage.client().complete_multipart_upload(
        Bucket=storage.bucket(),
        Key=upload.storage_key,
        UploadId=upload.s3_upload_id,
        MultipartUpload={
            "Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts]
        },
    )
    upload.status = "complete"
    if upload.kind == "video":
        db.add(VideoAsset(lesson_id=upload.lesson_id, storage_key=upload.storage_key))
    elif upload.kind == "transcript":
        db.add(
            TranscriptAsset(
                lesson_id=upload.lesson_id,
                storage_key=upload.storage_key,
                filename=upload.filename,
            )
        )
    else:
        db.add(
            DeckAsset(
                lesson_id=upload.lesson_id,
                storage_key=upload.storage_key,
                filename=upload.filename,
            )
        )
    db.commit()


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def abort_upload(upload_id: int, db: Session = Depends(get_sync_session)):
    upload = _found(db.get(Upload, upload_id), "Upload")
    if upload.status == "uploading":
        _abort(upload)
        db.commit()


@router.post("/lessons/{lesson_id}/save", response_model=CompleteOut)
def save_files(lesson_id: int, db: Session = Depends(get_sync_session)):
    """Sends the uploaded files on to processing, so upload order never matters.

    The page disables Save while its own uploads run, so any upload still open here was left by
    a closed tab, and it cannot be resumed.
    """
    lesson = db.scalars(select(Lesson).where(Lesson.id == lesson_id).with_for_update()).first()
    _found(lesson, "Lesson")
    if _newest(db, VideoAsset, lesson_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload a video first")
    revision_id = _start_pipeline(db, lesson)
    if revision_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing new to save")
    for upload in db.scalars(
        select(Upload).where(Upload.lesson_id == lesson_id, Upload.status == "uploading")
    ):
        _abort(upload)
    db.commit()
    advance(revision_id)
    return CompleteOut(revision_id=revision_id)


# Pipeline


@router.get("/revisions/{revision_id}/events")
async def revision_events(revision_id: int, db: AsyncSession = Depends(get_session)):
    _found(await db.get(LessonRevision, revision_id), "Revision")

    async def snapshot() -> RevisionOut:
        async with new_async_session() as session:
            revision = await session.get(LessonRevision, revision_id)
            lesson = await session.get(Lesson, revision.lesson_id)
            return await _revision_out(session, revision, lesson)

    async def stream():
        last = None
        while True:
            current = await snapshot()
            payload = current.model_dump_json()
            yield f"data: {payload}\n\n" if payload != last else ": keepalive\n\n"
            last = payload
            if current.status in FINAL_STATUSES:
                return
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/revisions/{revision_id}/stages/{name}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(revision_id: int, name: str, db: Session = Depends(get_sync_session)):
    stage = db.scalars(
        select(PipelineStage).where(
            PipelineStage.revision_id == revision_id, PipelineStage.name == name
        )
    ).first()
    _found(stage, "Stage")
    if stage.status not in ("failed", "waiting_for_llm"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This stage is not waiting for a retry")
    retry_stage(db, stage)
    db.commit()
    advance(revision_id)


# Review


@router.get("/revisions/{revision_id}/timeline", response_model=TimelineOut)
async def get_timeline(revision_id: int, db: AsyncSession = Depends(get_session)):
    revision = _found(await db.get(LessonRevision, revision_id), "Revision")
    video = await db.get(VideoAsset, revision.video_asset_id)
    slides = await slides_for(db, revision.deck_asset_id)
    numbers = {s.id: s.number for s in slides}
    rows = await db.scalars(
        select(SlideInterval)
        .where(SlideInterval.revision_id == revision_id)
        .order_by(SlideInterval.start_ms)
    )
    return TimelineOut(
        duration_ms=video.duration_ms or 0,
        slides=[slide_out(s) for s in slides],
        rows=[
            TimelineRow(
                start_ms=r.start_ms,
                end_ms=r.end_ms,
                slide=numbers.get(r.slide_id),
                confidence=r.confidence,
                method=r.method,
                source=r.source,
            )
            for r in rows
        ],
    )


def _check_timeline(rows: list[TimelineRow], duration_ms: int) -> None:
    if not rows or rows[0].start_ms != 0 or rows[-1].end_ms != duration_ms:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The timeline must cover the whole video"
        )
    for row, following in zip(rows, rows[1:], strict=False):
        if row.end_ms != following.start_ms:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Timeline rows must touch with no gaps"
            )
    if any(row.end_ms <= row.start_ms for row in rows):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A timeline row is empty")


RELINK_PASSAGES = text(
    """
    UPDATE passage p
    SET slide_id = (
        SELECT i.slide_id FROM slide_interval i
        WHERE i.revision_id = p.revision_id
          AND i.start_ms <= (p.start_ms + p.end_ms) / 2
          AND i.end_ms > (p.start_ms + p.end_ms) / 2
        LIMIT 1
    )
    WHERE p.revision_id = :revision_id
    """
)


@router.put("/revisions/{revision_id}/timeline", status_code=status.HTTP_204_NO_CONTENT)
async def put_timeline(
    revision_id: int, body: TimelineIn, db: AsyncSession = Depends(get_session)
):
    revision = _found(await db.get(LessonRevision, revision_id), "Revision")
    video = await db.get(VideoAsset, revision.video_asset_id)
    rows = sorted(body.rows, key=lambda r: r.start_ms)
    _check_timeline(rows, video.duration_ms or 0)

    slides = {s.number: s.id for s in await slides_for(db, revision.deck_asset_id)}
    if any(r.slide is not None and r.slide not in slides for r in rows):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown slide number")

    existing = {
        (r.start_ms, r.end_ms, r.slide_id): r
        for r in await db.scalars(
            select(SlideInterval).where(SlideInterval.revision_id == revision_id)
        )
    }
    keep: list[SlideInterval] = []
    for row in rows:
        slide_id = slides.get(row.slide)
        unchanged = existing.pop((row.start_ms, row.end_ms, slide_id), None)
        if unchanged is not None:
            keep.append(unchanged)
        else:
            keep.append(
                SlideInterval(
                    revision_id=revision_id,
                    start_ms=row.start_ms,
                    end_ms=row.end_ms,
                    slide_id=slide_id,
                    confidence=1.0,
                    method=row.method,
                    source="manual",
                )
            )
    for stale in existing.values():
        await db.delete(stale)
    db.add_all(keep)
    await db.flush()
    await db.execute(RELINK_PASSAGES, {"revision_id": revision_id})
    await db.commit()


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
async def edit_segment(
    segment_id: int, body: SegmentPatch, db: AsyncSession = Depends(get_session)
):
    segment = _found(await db.get(TranscriptSegment, segment_id), "Segment")
    segment.text_corrected = body.text
    segment.admin_edited = True
    await db.flush()

    revisions = list(
        await db.scalars(
            select(LessonRevision.id).where(
                LessonRevision.video_asset_id == segment.video_asset_id
            )
        )
    )
    passages = await db.scalars(
        select(Passage).where(
            Passage.revision_id.in_(revisions),
            Passage.first_seq <= segment.seq,
            Passage.last_seq >= segment.seq,
        )
    )
    touched = set()
    for passage in passages:
        lines = await db.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.video_asset_id == segment.video_asset_id,
                TranscriptSegment.seq.between(passage.first_seq, passage.last_seq),
            )
            .order_by(TranscriptSegment.seq)
        )
        passage.text = " ".join(line.display_text for line in lines)
        passage.embedding = None
        touched.add(passage.revision_id)
    await db.commit()
    for revision_id in touched:
        await run_in_threadpool(reembed_passages.delay, revision_id)
    return SegmentOut(
        id=segment.id,
        seq=segment.seq,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        text=segment.display_text,
    )


@router.post("/revisions/{revision_id}/publish", response_model=LessonOut)
def publish(revision_id: int, db: Session = Depends(get_sync_session)):
    revision = _found(db.get(LessonRevision, revision_id), "Revision")
    if revision.status not in ("needs_review", "published"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This revision is not ready to publish")
    lesson = db.get(Lesson, revision.lesson_id)
    lesson.active_revision_id = revision.id
    revision.status = "published"
    sync_lesson_status(db, revision)
    if lesson.status != "published":
        lesson.status = "published"
    db.commit()
    return lesson
