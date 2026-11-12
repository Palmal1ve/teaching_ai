from sqlalchemy import delete, select

from app.core.db import session_scope
from app.models import ExtractionUnit, Passage, SlideInterval, TranscriptSegment
from app.pipeline.context import StageContext

MIN_MS = 30_000
MAX_MS = 60_000


def slide_at(intervals: list[SlideInterval], ms: int) -> int | None:
    for interval in intervals:
        if interval.start_ms <= ms < interval.end_ms:
            return interval.slide_id
    return None


def group_segments(segments: list, intervals: list) -> list[list]:
    """30-60 second groups that never cross a slide change, preferring sentence ends."""
    groups: list[list] = []
    current: list = []
    current_slide = None
    for segment in segments:
        slide = slide_at(intervals, (segment.start_ms + segment.end_ms) // 2)
        if current:
            length = segment.end_ms - current[0].start_ms
            sentence_end = current[-1].display_text.rstrip().endswith((".", "?", "!"))
            spoken = current[-1].end_ms - current[0].start_ms
            if (
                slide != current_slide
                or length > MAX_MS
                or (spoken >= MIN_MS and sentence_end)
            ):
                groups.append(current)
                current = []
        if not current:
            current_slide = slide
        current.append(segment)
    if current:
        groups.append(current)
    return groups


def run(context: StageContext) -> None:
    with session_scope() as session:
        session.execute(delete(Passage).where(Passage.revision_id == context.revision_id))
        session.execute(
            delete(ExtractionUnit).where(ExtractionUnit.revision_id == context.revision_id)
        )
        segments = session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.video_asset_id == context.video_id)
            .order_by(TranscriptSegment.seq)
        ).all()
        intervals = session.scalars(
            select(SlideInterval)
            .where(SlideInterval.revision_id == context.revision_id)
            .order_by(SlideInterval.start_ms)
        ).all()
        for group in group_segments(segments, intervals):
            session.add(
                Passage(
                    revision_id=context.revision_id,
                    course_id=context.course_id,
                    first_seq=group[0].seq,
                    last_seq=group[-1].seq,
                    start_ms=group[0].start_ms,
                    end_ms=group[-1].end_ms,
                    slide_id=slide_at(intervals, (group[0].start_ms + group[0].end_ms) // 2),
                    text=" ".join(s.display_text for s in group),
                )
            )
