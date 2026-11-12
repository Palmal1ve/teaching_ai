"""Finds what to show GLM: where the student is, hybrid search, and graph expansion."""
from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.knowledge.extraction import normalise
from app.models import (
    Concept,
    ConceptEdge,
    EdgeEvidence,
    Lesson,
    LessonRevision,
    Passage,
    Slide,
    SlideInterval,
    Statement,
    StatementConcept,
    StatementEvidence,
    TranscriptSegment,
)

RRF_K = 60
SEARCH_LIMIT = 30
PLAYHEAD_WINDOW_MS = 90_000
CURRENT_LESSON_BOOST = 1.3
KIND_BOOST = {"exam_hint": 1.5, "correction": 1.5}
GRAPH_NEAR_DISTANCE = 0.35
GRAPH_NEAR_CONCEPTS = 3


@dataclass
class Source:
    key: tuple
    lesson_id: int
    lesson_position: int
    start_ms: int
    end_ms: int
    slide: int | None
    text: str
    quote: str
    kind: str | None = None


def visible_revisions(
    session: Session, course_id: int, preview: LessonRevision | None = None
) -> dict[int, Lesson]:
    """Active revisions only. An admin previewing a draft sees it in place of the live one."""
    lessons = session.scalars(select(Lesson).where(Lesson.course_id == course_id)).all()
    visible = {}
    for lesson in lessons:
        if preview is not None and preview.lesson_id == lesson.id:
            visible[preview.id] = lesson
        elif lesson.active_revision_id:
            visible[lesson.active_revision_id] = lesson
    return visible


def _or_query(question: str):
    """English stemming, but any word may match: a question rarely contains all of a passage."""
    return func.to_tsquery(
        "english",
        func.replace(cast(func.plainto_tsquery("english", question), String), "&", "|"),
    )


def _vector_ids(session, model, course_id, revisions, vector) -> list[int]:
    return list(
        session.scalars(
            select(model.id)
            .where(
                model.course_id == course_id,
                model.revision_id.in_(revisions),
                model.embedding.is_not(None),
            )
            .order_by(model.embedding.cosine_distance(vector))
            .limit(SEARCH_LIMIT)
        )
    )


def _text_ids(session, model, course_id, revisions, question) -> list[int]:
    query = _or_query(question)
    return list(
        session.scalars(
            select(model.id)
            .where(
                model.course_id == course_id,
                model.revision_id.in_(revisions),
                model.tsv.op("@@")(query),
            )
            .order_by(func.ts_rank_cd(model.tsv, query).desc())
            .limit(SEARCH_LIMIT)
        )
    )


def _supported_concepts(course_id: int, revisions: list[int]):
    return (
        select(StatementConcept.concept_id)
        .join(Statement, Statement.id == StatementConcept.statement_id)
        .where(Statement.course_id == course_id, Statement.revision_id.in_(revisions))
    )


def matched_concepts(session, course_id, revisions, question, vector) -> set[int]:
    """Concepts named in the question, plus the nearest by meaning. Active ones only."""
    supported = _supported_concepts(course_id, revisions)
    words = f" {normalise(question)} "
    concepts = session.scalars(
        select(Concept).where(Concept.course_id == course_id, Concept.id.in_(supported))
    ).all()
    found = {
        c.id
        for c in concepts
        if any(f" {normalise(name)} " in words for name in [c.name, *c.aliases])
    }
    distance = Concept.embedding.cosine_distance(vector)
    near = session.scalars(
        select(Concept.id)
        .where(
            Concept.course_id == course_id,
            Concept.id.in_(supported),
            Concept.embedding.is_not(None),
            distance < GRAPH_NEAR_DISTANCE,
        )
        .order_by(distance)
        .limit(GRAPH_NEAR_CONCEPTS)
    ).all()
    return found | set(near)


def _neighbours(session, concept_ids, course_id, revisions, types=None) -> set[int]:
    if not concept_ids:
        return set()
    supported_edges = (
        select(EdgeEvidence.edge_id)
        .join(Statement, Statement.id == EdgeEvidence.statement_id)
        .where(Statement.course_id == course_id, Statement.revision_id.in_(revisions))
    )
    query = select(ConceptEdge).where(
        ConceptEdge.course_id == course_id,
        ConceptEdge.id.in_(supported_edges),
        or_(ConceptEdge.source_id.in_(concept_ids), ConceptEdge.target_id.in_(concept_ids)),
    )
    if types:
        query = query.where(ConceptEdge.type.in_(types))
    result: set[int] = set()
    for edge in session.scalars(query):
        result.update((edge.source_id, edge.target_id))
    return result - set(concept_ids)


def graph_statement_ids(session, course_id, revisions, question, vector) -> list[int]:
    """One hop on every relation, and a second hop along PREREQUISITE_OF."""
    seeds = matched_concepts(session, course_id, revisions, question, vector)
    first_hop = _neighbours(session, seeds, course_id, revisions)
    prerequisites = _neighbours(session, seeds, course_id, revisions, ["PREREQUISITE_OF"])
    second_hop = _neighbours(session, prerequisites, course_id, revisions, ["PREREQUISITE_OF"])
    ordered = [*seeds, *(first_hop - seeds), *(second_hop - seeds - first_hop)]
    if not ordered:
        return []
    rank = {concept_id: index for index, concept_id in enumerate(ordered)}
    rows = session.execute(
        select(StatementConcept.statement_id, StatementConcept.concept_id)
        .join(Statement, Statement.id == StatementConcept.statement_id)
        .where(
            StatementConcept.concept_id.in_(ordered),
            Statement.course_id == course_id,
            Statement.revision_id.in_(revisions),
        )
    ).all()
    best: dict[int, int] = {}
    for statement_id, concept_id in rows:
        best[statement_id] = min(best.get(statement_id, len(ordered)), rank[concept_id])
    return sorted(best, key=best.get)[:SEARCH_LIMIT]


def fuse(rankings: list[list[tuple]]) -> dict[tuple, float]:
    """Reciprocal Rank Fusion: position in each list counts, raw scores never do."""
    scores: dict[tuple, float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + position + 1)
    return scores


def _passage_sources(session, ids, revisions) -> dict[tuple, Source]:
    if not ids:
        return {}
    rows = session.execute(
        select(Passage, Slide.number)
        .outerjoin(Slide, Slide.id == Passage.slide_id)
        .where(Passage.id.in_(ids))
    ).all()
    sources = {}
    for passage, number in rows:
        lesson = revisions[passage.revision_id]
        sources[("passage", passage.id)] = Source(
            key=("passage", passage.id),
            lesson_id=lesson.id,
            lesson_position=lesson.position,
            start_ms=passage.start_ms,
            end_ms=passage.end_ms,
            slide=number,
            text=passage.text,
            quote=passage.text[:200],
        )
    return sources


def _statement_sources(session, ids, revisions) -> dict[tuple, Source]:
    if not ids:
        return {}
    rows = session.execute(
        select(Statement, StatementEvidence, Slide.number)
        .join(StatementEvidence, StatementEvidence.statement_id == Statement.id)
        .join(Passage, Passage.id == StatementEvidence.passage_id)
        .outerjoin(Slide, Slide.id == Passage.slide_id)
        .where(Statement.id.in_(ids))
        .order_by(StatementEvidence.start_ms.desc())
    ).all()
    sources = {}
    for statement, evidence, number in rows:
        lesson = revisions[statement.revision_id]
        sources[("statement", statement.id)] = Source(
            key=("statement", statement.id),
            lesson_id=lesson.id,
            lesson_position=lesson.position,
            start_ms=evidence.start_ms,
            end_ms=evidence.end_ms,
            slide=number,
            text=f'{statement.text}\nThe professor said: "{evidence.quote}"',
            quote=evidence.quote,
            kind=statement.kind,
        )
    return sources


def playhead_source(
    session: Session, revision: LessonRevision, lesson: Lesson, current_ms: int
) -> Source | None:
    """The current slide and the last 90 seconds, so "what did they just say?" works."""
    segments = session.scalars(
        select(TranscriptSegment)
        .where(
            TranscriptSegment.video_asset_id == revision.video_asset_id,
            TranscriptSegment.end_ms > current_ms - PLAYHEAD_WINDOW_MS,
            TranscriptSegment.start_ms <= current_ms,
        )
        .order_by(TranscriptSegment.seq)
    ).all()
    slide = session.scalars(
        select(Slide)
        .join(SlideInterval, SlideInterval.slide_id == Slide.id)
        .where(
            SlideInterval.revision_id == revision.id,
            SlideInterval.start_ms <= current_ms,
            SlideInterval.end_ms > current_ms,
        )
    ).first()
    spoken = " ".join(s.display_text for s in segments)
    if not spoken and slide is None:
        return None
    body = spoken
    if slide is not None:
        parts = [slide.text, slide.ocr_text]
        if slide.notes:
            parts.append(f"Speaker notes: {slide.notes}")
        visible = "\n".join(p for p in parts if p.strip())
        body = f"Slide on screen now:\n{visible}\n\nJust said:\n{spoken}"
    start_ms = segments[0].start_ms if segments else current_ms
    return Source(
        key=("playhead", lesson.id),
        lesson_id=lesson.id,
        lesson_position=lesson.position,
        start_ms=start_ms,
        end_ms=current_ms,
        slide=slide.number if slide else None,
        text=body,
        quote=spoken[:200],
        kind="playhead",
    )


def retrieve(
    session: Session,
    course_id: int,
    lesson: Lesson,
    revisions: dict[int, Lesson],
    question: str,
    vector: list[float],
    current_ms: int,
) -> list[Source]:
    revision_ids = list(revisions)
    if not revision_ids:
        return []
    passage_vector = _vector_ids(session, Passage, course_id, revision_ids, vector)
    passage_text = _text_ids(session, Passage, course_id, revision_ids, question)
    statement_vector = _vector_ids(session, Statement, course_id, revision_ids, vector)
    statement_text = _text_ids(session, Statement, course_id, revision_ids, question)
    statement_graph = graph_statement_ids(session, course_id, revision_ids, question, vector)

    scores = fuse(
        [
            [("passage", i) for i in passage_vector],
            [("passage", i) for i in passage_text],
            [("statement", i) for i in statement_vector],
            [("statement", i) for i in statement_text],
            [("statement", i) for i in statement_graph],
        ]
    )
    sources = {
        **_passage_sources(
            session, [k[1] for k in scores if k[0] == "passage"], revisions
        ),
        **_statement_sources(
            session, [k[1] for k in scores if k[0] == "statement"], revisions
        ),
    }
    for key, source in sources.items():
        if source.lesson_id == lesson.id:
            scores[key] *= CURRENT_LESSON_BOOST
        scores[key] *= KIND_BOOST.get(source.kind, 1.0)

    ranked = sorted(sources.values(), key=lambda s: -scores[s.key])
    current_revision = next((r for r, owner in revisions.items() if owner.id == lesson.id), None)
    if current_revision is not None:
        playhead = playhead_source(
            session, session.get(LessonRevision, current_revision), lesson, current_ms
        )
        if playhead is not None:
            ranked.insert(0, playhead)

    budget = get_settings().context_token_budget * 4
    chosen, used = [], 0
    for source in ranked:
        used += len(source.text)
        if used > budget and chosen:
            break
        chosen.append(source)
    return chosen
