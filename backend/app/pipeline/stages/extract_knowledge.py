import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.llm import LLMCall, get_llm, usage_rows
from app.knowledge.extraction import (
    SYSTEM,
    UNIT_MAX_MS,
    Extraction,
    Unit,
    apply_fix,
    build_prompt,
    verify,
)
from app.models import ExtractionUnit, Passage, Slide, TranscriptSegment
from app.pipeline.context import StageContext

log = logging.getLogger(__name__)


def group_passages(passages: list[Passage]) -> list[list[Passage]]:
    """One group per slide interval, or per 5 minutes when a span runs long or has no slide."""
    groups: list[list[Passage]] = []
    for passage in passages:
        current = groups[-1] if groups else None
        if (
            current
            and current[0].slide_id == passage.slide_id
            and passage.end_ms - current[0].start_ms <= UNIT_MAX_MS
        ):
            current.append(passage)
        else:
            groups.append([passage])
    return groups


def _load_units(context: StageContext) -> tuple[list[Unit], set[int]]:
    with session_scope() as session:
        passages = session.scalars(
            select(Passage)
            .where(Passage.revision_id == context.revision_id)
            .order_by(Passage.start_ms)
        ).all()
        segments = dict(
            session.execute(
                select(TranscriptSegment.seq, TranscriptSegment.text).where(
                    TranscriptSegment.video_asset_id == context.video_id
                )
            ).all()
        )
        slides = {
            s.id: f"{s.text}\n{s.ocr_text}\nSpeaker notes: {s.notes}"
            for s in session.scalars(select(Slide).where(Slide.deck_asset_id == context.deck_id))
        }
        done = set(
            session.scalars(
                select(ExtractionUnit.unit_index).where(
                    ExtractionUnit.revision_id == context.revision_id
                )
            )
        )
    units = []
    for index, group in enumerate(group_passages(passages)):
        seqs = range(group[0].first_seq, group[-1].last_seq + 1)
        units.append(
            Unit(
                index=index,
                segments={seq: segments[seq] for seq in seqs if seq in segments},
                slide_text=slides.get(group[0].slide_id, ""),
            )
        )
    return units, done


def _apply_term_fixes(context: StageContext) -> None:
    with session_scope() as session:
        fixes = [
            fix
            for result in session.scalars(
                select(ExtractionUnit.result).where(
                    ExtractionUnit.revision_id == context.revision_id
                )
            )
            for fix in result["term_fixes"]
        ]
        if not fixes:
            return
        segments = session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.video_asset_id == context.video_id,
                TranscriptSegment.admin_edited.is_(False),
            )
            .order_by(TranscriptSegment.seq)
        ).all()
        for segment in segments:
            fixed = segment.text
            for fix in fixes:
                fixed = apply_fix(fixed, fix["heard"], fix["correct"])
            segment.text_corrected = fixed if fixed != segment.text else None
        session.flush()
        by_seq = {s.seq: s for s in segments}
        for passage in session.scalars(
            select(Passage).where(Passage.revision_id == context.revision_id)
        ):
            seqs = range(passage.first_seq, passage.last_seq + 1)
            passage.text = " ".join(by_seq[s].display_text for s in seqs if s in by_seq)


def run(context: StageContext) -> None:
    units, done = _load_units(context)
    llm = get_llm()
    max_tokens = get_settings().extraction_max_tokens
    invalid = 0
    for unit in units:
        if unit.index in done:
            continue
        calls: list[LLMCall] = []
        reply = llm.complete_json(
            SYSTEM, build_prompt(unit), Extraction, max_tokens=max_tokens, calls=calls
        )
        with session_scope() as session:
            session.add_all(usage_rows("extraction", llm.model, calls, context.lesson_id))
            if reply is None:
                invalid += 1
                log.warning(
                    "Unit %s of revision %s: invalid reply", unit.index, context.revision_id
                )
                continue
            result, rejected = verify(reply, unit)
            if rejected:
                log.info("Unit %s: rejected %s unproven statements", unit.index, rejected)
            session.add(
                ExtractionUnit(
                    revision_id=context.revision_id, unit_index=unit.index, result=result
                )
            )
    if units and invalid * 2 > len(units):
        raise RuntimeError(f"GLM gave invalid replies for {invalid} of {len(units)} units")
    _apply_term_fixes(context)
