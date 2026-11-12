"""Merges concepts from one revision into the course graph."""
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.embeddings import embed
from app.core.llm import LLMCall, usage_rows
from app.knowledge.extraction import normalise
from app.models import Concept

NEAR_MATCH_DISTANCE = 0.4
CANDIDATES = 5

MERGE_SYSTEM = """Decide whether a new concept from a lecture is the same topic as an existing one
in the same course. They are the same only when either name could replace the other in any
sentence without changing its meaning, as with an abbreviation, a spelling variant or a rephrasing
of one name. A part, a step, a property, a special case, an opposite, or a related topic is a
different topic. Reply with the id of the matching concept, or null if none match. When unsure,
reply null."""


class MergeDecision(BaseModel):
    merge_with: int | None = None


def _names(name: str, aliases: list[str]) -> str:
    return f"{name} (also called {', '.join(aliases)})" if aliases else name


def merge_prompt(name: str, aliases: list[str], candidates: list[Concept]) -> str:
    """Names only: summaries describe related topics in overlapping words, and GLM then merges
    a part into its whole."""
    listing = "\n".join(f"{c.id}: {_names(c.name, c.aliases)}" for c in candidates)
    return f"New concept: {_names(name, aliases)}\n\nExisting concepts:\n{listing}"


def _pick(llm, name: str, aliases: list[str], candidates: list[Concept], calls) -> Concept | None:
    decision = llm.complete_json(
        MERGE_SYSTEM,
        merge_prompt(name, aliases, candidates),
        MergeDecision,
        max_tokens=get_settings().extraction_max_tokens,
        calls=calls,
    )
    if decision is None:
        return None
    return next((c for c in candidates if c.id == decision.merge_with), None)


def decide_merge(
    llm, name: str, aliases: list[str], candidates: list[Concept], calls: list[LLMCall]
) -> Concept | None:
    """GLM's pick from a list is noisy and sometimes merges a part into its whole. Its answer on
    one pair is stable, so a pick from several candidates stands only if GLM confirms it alone."""
    match = _pick(llm, name, aliases, candidates, calls)
    if match is None or len(candidates) == 1:
        return match
    return _pick(llm, name, aliases, [match], calls)


class ConceptResolver:
    def __init__(
        self, session: Session, course_id: int, llm, lesson_id: int | None = None
    ) -> None:
        self.session = session
        self.course_id = course_id
        self.llm = llm
        self.lesson_id = lesson_id
        self.by_name: dict[str, Concept] = {}
        for concept in session.scalars(select(Concept).where(Concept.course_id == course_id)):
            self._index(concept)

    def _index(self, concept: Concept) -> None:
        for name in [concept.name, *concept.aliases]:
            self.by_name.setdefault(normalise(name), concept)

    def _absorb(self, concept: Concept, name: str, aliases: list[str], summary: str) -> Concept:
        known = {normalise(a) for a in [concept.name, *concept.aliases]}
        fresh = [a for a in dict.fromkeys([name, *aliases]) if normalise(a) not in known]
        if fresh:
            concept.aliases = [*concept.aliases, *fresh]
        if summary and not concept.summary:
            concept.summary = summary
        self._index(concept)
        return concept

    def _near_matches(self, vector: list[float]) -> list[Concept]:
        distance = Concept.embedding.cosine_distance(vector)
        return list(
            self.session.scalars(
                select(Concept)
                .where(
                    Concept.course_id == self.course_id,
                    Concept.embedding.is_not(None),
                    distance < NEAR_MATCH_DISTANCE,
                )
                .order_by(distance)
                .limit(CANDIDATES)
            )
        )

    def resolve(self, name: str, aliases: list[str], summary: str) -> Concept:
        for candidate in [name, *aliases]:
            match = self.by_name.get(normalise(candidate))
            if match is not None:
                return self._absorb(match, name, aliases, summary)

        vector = embed([f"{name}: {summary}"])[0]
        candidates = self._near_matches(vector)
        match = None
        if candidates:
            calls: list[LLMCall] = []
            match = decide_merge(self.llm, name, aliases, candidates, calls)
            self.session.add_all(
                usage_rows("concept_merge", self.llm.model, calls, self.lesson_id)
            )
        if match is not None:
            return self._absorb(match, name, aliases, summary)

        concept = Concept(
            course_id=self.course_id,
            name=name,
            aliases=list(dict.fromkeys(aliases)),
            summary=summary,
            embedding=vector,
        )
        self.session.add(concept)
        self.session.flush()
        self._index(concept)
        return concept
