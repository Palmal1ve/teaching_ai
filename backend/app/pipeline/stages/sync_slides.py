import json

from sqlalchemy import delete, select

from app.core import storage
from app.core.db import session_scope
from app.core.embeddings import embed
from app.models import Slide, SlideInterval, TranscriptSegment, VideoAsset
from app.pipeline.context import StageContext
from app.sync.align import align
from app.sync.compute import score_matrix


def run(context: StageContext) -> None:
    with session_scope() as session:
        video = session.get(VideoAsset, context.video_id)
        shots_key, duration_ms = video.shots_key, video.duration_ms
        slides = session.scalars(
            select(Slide).where(Slide.deck_asset_id == context.deck_id).order_by(Slide.number)
        ).all()
        segments = [
            {"start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.display_text}
            for s in session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.video_asset_id == context.video_id)
                .order_by(TranscriptSegment.seq)
            )
        ]

    shots = json.loads(storage.read_bytes(shots_key))
    slide_texts = [f"{s.text}\n{s.ocr_text}" for s in slides]
    spoken_texts = [f"{s.text}\n{s.notes}\n{s.ocr_text}" for s in slides]
    scores = score_matrix(
        [storage.read_bytes(shot["key"]) for shot in shots],
        [storage.read_bytes(s.image_key) for s in slides],
        slide_texts,
    )
    timeline = align(shots, scores, segments, spoken_texts, duration_ms, embed)

    with session_scope() as session:
        session.execute(
            delete(SlideInterval).where(SlideInterval.revision_id == context.revision_id)
        )
        session.add_all(
            SlideInterval(
                revision_id=context.revision_id,
                start_ms=row.start_ms,
                end_ms=row.end_ms,
                slide_id=None if row.slide is None else slides[row.slide].id,
                confidence=round(row.confidence, 3),
                method=row.method,
            )
            for row in timeline
        )
