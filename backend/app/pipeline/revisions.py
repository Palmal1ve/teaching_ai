"""Creating revisions, and keeping lesson.status in step with the newest one."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import DeckAsset, Lesson, LessonRevision, PipelineStage, TranscriptAsset, VideoAsset
from app.pipeline.graph import DECK_ONLY, STAGES

CANCELLABLE = ("pending", "queued", "waiting_for_llm")


def _already_produced(video: VideoAsset, deck: DeckAsset | None) -> set[str]:
    produced = {
        "probe": video.duration_ms is not None,
        "transcode_hls": video.hls_key is not None,
        "extract_audio": video.audio_key is not None,
        "transcribe": video.transcribed_at is not None,
        "sample_frames": video.shots_key is not None,
        "render_deck": deck is not None and deck.slide_count is not None,
        "read_slides": deck is not None and deck.ocr_at is not None,
    }
    return {name for name, done in produced.items() if done}


def stage_already_produced(session: Session, stage: PipelineStage) -> bool:
    revision = session.get(LessonRevision, stage.revision_id)
    video = session.get(VideoAsset, revision.video_asset_id)
    deck = session.get(DeckAsset, revision.deck_asset_id) if revision.deck_asset_id else None
    return stage.name in _already_produced(video, deck)


def supersede_unpublished(session: Session, lesson: Lesson) -> None:
    stale = session.scalars(
        select(LessonRevision.id).where(
            LessonRevision.lesson_id == lesson.id,
            LessonRevision.status.in_(("processing", "failed", "needs_review")),
        )
    ).all()
    if not stale:
        return
    session.execute(
        update(LessonRevision).where(LessonRevision.id.in_(stale)).values(status="superseded")
    )
    session.execute(
        update(PipelineStage)
        .where(PipelineStage.revision_id.in_(stale), PipelineStage.status.in_(CANCELLABLE))
        .values(status="cancelled")
    )


def create_revision(
    session: Session, lesson: Lesson, video: VideoAsset, deck: DeckAsset | None
) -> LessonRevision:
    supersede_unpublished(session, lesson)
    revision = LessonRevision(
        lesson_id=lesson.id, video_asset_id=video.id, deck_asset_id=deck.id if deck else None
    )
    session.add(revision)
    session.flush()
    reused = _already_produced(video, deck)
    transcript = (
        session.get(TranscriptAsset, video.transcript_asset_id)
        if video.transcript_asset_id
        else None
    )
    # An .srt or .vtt brings its own times. A PDF may not, and then Whisper needs the audio.
    timed = transcript is not None and not transcript.storage_key.endswith(".pdf")
    for name in STAGES:
        skip = (
            name in reused
            or (deck is None and name in DECK_ONLY)
            or (timed and name == "extract_audio")
        )
        session.add(
            PipelineStage(
                revision_id=revision.id, name=name, status="skipped" if skip else "pending"
            )
        )
    lesson.status = "processing"
    return revision


def latest_revision(session: Session, lesson_id: int) -> LessonRevision | None:
    return session.scalars(
        select(LessonRevision)
        .where(LessonRevision.lesson_id == lesson_id)
        .order_by(LessonRevision.id.desc())
        .limit(1)
    ).first()


def sync_lesson_status(session: Session, revision: LessonRevision) -> None:
    latest = latest_revision(session, revision.lesson_id)
    if latest is not None and latest.id == revision.id:
        session.get(Lesson, revision.lesson_id).status = revision.status
