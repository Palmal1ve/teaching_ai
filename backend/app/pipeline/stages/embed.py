from sqlalchemy import select

from app.core.db import session_scope
from app.core.embeddings import embed
from app.models import Concept, Passage, Statement
from app.pipeline.context import StageContext


def _fill(rows: list, texts: list[str]) -> None:
    for row, vector in zip(rows, embed(texts) if texts else [], strict=True):
        row.embedding = vector


def embed_missing(revision_id: int) -> None:
    with session_scope() as session:
        passages = session.scalars(
            select(Passage).where(Passage.revision_id == revision_id, Passage.embedding.is_(None))
        ).all()
        statements = session.scalars(
            select(Statement).where(
                Statement.revision_id == revision_id, Statement.embedding.is_(None)
            )
        ).all()
        _fill(passages, [p.text for p in passages])
        _fill(statements, [s.text for s in statements])


def run(context: StageContext) -> None:
    embed_missing(context.revision_id)
    with session_scope() as session:
        concepts = session.scalars(
            select(Concept).where(
                Concept.course_id == context.course_id, Concept.embedding.is_(None)
            )
        ).all()
        _fill(concepts, [f"{c.name}: {c.summary}" for c in concepts])
