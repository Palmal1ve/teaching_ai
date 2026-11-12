from sqlalchemy import delete, func, select

from app.core.db import session_scope
from app.core.llm import get_llm
from app.knowledge.extraction import normalise
from app.knowledge.resolution import ConceptResolver
from app.models import (
    ConceptEdge,
    EdgeEvidence,
    ExtractionUnit,
    Passage,
    Statement,
    StatementConcept,
    StatementEvidence,
    TranscriptSegment,
)
from app.pipeline.context import StageContext


def _edge(session, course_id: int, source_id: int, target_id: int, kind: str) -> ConceptEdge:
    edge = session.scalars(
        select(ConceptEdge).where(
            ConceptEdge.course_id == course_id,
            ConceptEdge.source_id == source_id,
            ConceptEdge.target_id == target_id,
            ConceptEdge.type == kind,
        )
    ).first()
    if edge is None:
        edge = ConceptEdge(
            course_id=course_id, source_id=source_id, target_id=target_id, type=kind
        )
        session.add(edge)
        session.flush()
    return edge


def _evidence(statement_id, data, passages, times) -> list[StatementEvidence]:
    rows: dict[int, StatementEvidence] = {}
    for seq in sorted(data["segment_ids"]):
        passage = next((p for p in passages if p.first_seq <= seq <= p.last_seq), None)
        if passage is None or seq not in times:
            continue
        start_ms, end_ms = times[seq]
        row = rows.get(passage.id)
        if row is None:
            rows[passage.id] = StatementEvidence(
                statement_id=statement_id,
                passage_id=passage.id,
                start_ms=start_ms,
                end_ms=end_ms,
                quote=data["quote"],
            )
        else:
            row.end_ms = max(row.end_ms, end_ms)
    return list(rows.values())


def _linked_names(index: int, data: dict, unit: dict) -> set[str]:
    """GLM's list, plus concepts the statement's relations name or its text mentions.
    GLM often leaves the list empty, and an unlinked concept is invisible to the graph."""
    names = set(data["concepts"])
    for relation in unit["relations"]:
        if relation["statement_index"] == index:
            names.update((relation["source"], relation["target"]))
    text = f" {normalise(data['text'])} "
    for concept in unit["concepts"]:
        if any(f" {normalise(n)} " in text for n in [concept["name"], *concept["aliases"]]):
            names.add(concept["name"])
    return names


def run(context: StageContext) -> None:
    with session_scope() as session:
        session.execute(select(func.pg_advisory_xact_lock(context.course_id)))
        session.execute(delete(Statement).where(Statement.revision_id == context.revision_id))

        passages = session.scalars(
            select(Passage).where(Passage.revision_id == context.revision_id)
        ).all()
        times = {
            row.seq: (row.start_ms, row.end_ms)
            for row in session.execute(
                select(
                    TranscriptSegment.seq, TranscriptSegment.start_ms, TranscriptSegment.end_ms
                ).where(TranscriptSegment.video_asset_id == context.video_id)
            )
        }
        units = session.scalars(
            select(ExtractionUnit.result)
            .where(ExtractionUnit.revision_id == context.revision_id)
            .order_by(ExtractionUnit.unit_index)
        ).all()

        resolver = ConceptResolver(session, context.course_id, get_llm(), context.lesson_id)
        for unit in units:
            concepts = {
                c["name"]: resolver.resolve(c["name"], c["aliases"], c["summary"])
                for c in unit["concepts"]
            }
            statement_ids = []
            for index, data in enumerate(unit["statements"]):
                statement = Statement(
                    revision_id=context.revision_id,
                    course_id=context.course_id,
                    kind=data["kind"],
                    text=data["text"],
                )
                session.add(statement)
                session.flush()
                statement_ids.append(statement.id)
                session.add_all(_evidence(statement.id, data, passages, times))
                linked = {
                    concepts[n].id for n in _linked_names(index, data, unit) if n in concepts
                }
                session.add_all(
                    StatementConcept(statement_id=statement.id, concept_id=concept_id)
                    for concept_id in linked
                )
            for relation in unit["relations"]:
                source = concepts.get(relation["source"])
                target = concepts.get(relation["target"])
                if source is None or target is None or source.id == target.id:
                    continue
                edge = _edge(session, context.course_id, source.id, target.id, relation["type"])
                statement_id = statement_ids[relation["statement_index"]]
                exists = session.scalars(
                    select(EdgeEvidence.id).where(
                        EdgeEvidence.edge_id == edge.id,
                        EdgeEvidence.statement_id == statement_id,
                    )
                ).first()
                if exists is None:
                    session.add(EdgeEvidence(edge_id=edge.id, statement_id=statement_id))
