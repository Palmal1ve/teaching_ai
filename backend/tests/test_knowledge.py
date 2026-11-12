from sqlalchemy import func, select

from app.assistant.retrieval import graph_statement_ids, retrieve, visible_revisions
from app.core.db import session_scope
from app.knowledge.extraction import Extraction, Unit, verify
from app.knowledge import resolution
from app.knowledge.resolution import ConceptResolver, MergeDecision
from app.models import (
    Concept,
    ConceptEdge,
    EdgeEvidence,
    ExtractionUnit,
    LLMUsage,
    Statement,
    StatementConcept,
)
from app.pipeline import runner
from app.pipeline.context import StageContext
from app.pipeline.stages import resolve_concepts
from tests.conftest import add_passage, add_statement, fake_vector, make_lesson, make_revision


def context_for(revision, lesson):
    return StageContext(
        revision.id, lesson.id, lesson.course_id, revision.video_asset_id, revision.deck_asset_id
    )


def concept(session, course_id, name, aliases=(), text=None):
    row = Concept(
        course_id=course_id,
        name=name,
        aliases=list(aliases),
        embedding=fake_vector(text or name),
    )
    session.add(row)
    session.flush()
    return row


def link(session, statement, row):
    session.add(StatementConcept(statement_id=statement.id, concept_id=row.id))
    session.flush()


def edge(session, course_id, source, target, kind, statement):
    row = ConceptEdge(course_id=course_id, source_id=source.id, target_id=target.id, type=kind)
    session.add(row)
    session.flush()
    session.add(EdgeEvidence(edge_id=row.id, statement_id=statement.id))
    session.flush()
    return row


def test_exact_alias_merges_without_asking_glm(llm):
    with session_scope() as session:
        lesson = make_lesson(session)
        concept(session, lesson.course_id, "Gradient descent", ["GD"])
        resolver = ConceptResolver(session, lesson.course_id, llm)
        merged = resolver.resolve("gd", ["steepest descent"], "")
        assert merged.name == "Gradient descent"
        assert "steepest descent" in merged.aliases
        assert session.scalar(select(func.count(Concept.id))) == 1


def test_near_match_goes_to_glm_and_merges_on_yes(llm):
    with session_scope() as session:
        lesson = make_lesson(session)
        existing = concept(
            session, lesson.course_id, "Edge relaxation",
            text="Relaxing: updating shortest distance estimates",
        )
        llm.structured = [MergeDecision(merge_with=existing.id)]
        resolver = ConceptResolver(session, lesson.course_id, llm)
        merged = resolver.resolve("Relaxing", [], "updating shortest distance estimates")
        assert merged.id == existing.id


def at_distance(vector, distance):
    """A unit vector at this cosine distance from `vector`, which must be a unit vector."""
    similarity = 1 - distance
    other = [0.0] * len(vector)
    other[vector.index(0.0)] = (1 - similarity**2) ** 0.5
    return [similarity * v + o for v, o in zip(vector, other, strict=True)]


def unit_vector(size):
    return [1.0] + [0.0] * (size - 1)


def test_pair_like_bellman_ford_at_distance_0_344_reaches_glm_and_merges(llm, monkeypatch):
    base = unit_vector(len(fake_vector("x")))
    monkeypatch.setattr(resolution, "embed", lambda texts: [at_distance(base, 0.344)])
    with session_scope() as session:
        lesson = make_lesson(session)
        existing = concept(session, lesson.course_id, "Bellman-Ford algorithm")
        existing.embedding = base
        session.flush()
        llm.structured = [MergeDecision(merge_with=existing.id)]
        resolver = ConceptResolver(session, lesson.course_id, llm, lesson.id)
        assert resolver.resolve("Bellman Ford", [], "Handles negative edges").id == existing.id
        assert "Bellman Ford" in existing.aliases
        usage = session.scalars(select(LLMUsage)).one()
        assert usage.purpose == "concept_merge" and usage.lesson_id == lesson.id


def test_merge_prompt_shows_names_and_aliases_but_not_summaries():
    candidates = [Concept(id=7, name="Gradient descent", aliases=["GD"], summary="Steps downhill.")]
    prompt = resolution.merge_prompt("Steepest descent", [], candidates)
    assert "7: Gradient descent (also called GD)" in prompt and "downhill" not in prompt


def test_pick_from_several_candidates_must_be_confirmed_alone(llm, monkeypatch):
    base = unit_vector(len(fake_vector("x")))
    monkeypatch.setattr(resolution, "embed", lambda texts: [at_distance(base, 0.2)])
    with session_scope() as session:
        lesson = make_lesson(session)
        whole = concept(session, lesson.course_id, "Bellman Ford")
        other = concept(session, lesson.course_id, "Negative edges")
        whole.embedding = other.embedding = base
        session.flush()
        llm.structured = [MergeDecision(merge_with=whole.id), MergeDecision(merge_with=None)]
        resolver = ConceptResolver(session, lesson.course_id, llm)
        part = resolver.resolve("Negative cycle detection", [], "")
        assert part.id not in {whole.id, other.id}
        assert session.scalar(select(func.count(LLMUsage.id))) == 2


def test_confirmed_pick_from_several_candidates_merges(llm, monkeypatch):
    base = unit_vector(len(fake_vector("x")))
    monkeypatch.setattr(resolution, "embed", lambda texts: [at_distance(base, 0.2)])
    with session_scope() as session:
        lesson = make_lesson(session)
        same = concept(session, lesson.course_id, "Bellman-Ford algorithm")
        other = concept(session, lesson.course_id, "Edge relaxation")
        same.embedding = other.embedding = base
        session.flush()
        llm.structured = [MergeDecision(merge_with=same.id), MergeDecision(merge_with=same.id)]
        resolver = ConceptResolver(session, lesson.course_id, llm)
        assert resolver.resolve("Bellman Ford", [], "").id == same.id


def test_distant_concept_is_never_sent_to_glm(llm, monkeypatch):
    base = unit_vector(len(fake_vector("x")))
    monkeypatch.setattr(resolution, "embed", lambda texts: [at_distance(base, 0.5)])
    with session_scope() as session:
        lesson = make_lesson(session)
        existing = concept(session, lesson.course_id, "Heap")
        existing.embedding = base
        session.flush()
        decision = MergeDecision(merge_with=existing.id)
        llm.structured = [decision]
        resolved = ConceptResolver(session, lesson.course_id, llm).resolve("Hashing", [], "")
        assert resolved.id != existing.id and llm.structured == [decision]


def test_near_match_stays_separate_on_no(llm):
    with session_scope() as session:
        lesson = make_lesson(session)
        concept(session, lesson.course_id, "Heap", text="Binary heap: a tree structure")
        llm.structured = [MergeDecision(merge_with=None)]
        resolver = ConceptResolver(session, lesson.course_id, llm)
        resolver.resolve("Binary heap", [], "a tree structure")
        assert session.scalar(select(func.count(Concept.id))) == 2


def test_glm_cannot_merge_with_a_concept_that_was_not_offered(llm):
    with session_scope() as session:
        lesson = make_lesson(session)
        concept(session, lesson.course_id, "Heap", text="Binary heap: a tree structure")
        llm.structured = [MergeDecision(merge_with=999_999)]
        resolver = ConceptResolver(session, lesson.course_id, llm)
        assert resolver.resolve("Binary heap", [], "a tree structure").name == "Binary heap"


def test_concepts_never_merge_across_courses(llm):
    with session_scope() as session:
        first = make_lesson(session)
        second = make_lesson(session)
        concept(session, first.course_id, "Heap")
        resolved = ConceptResolver(session, second.course_id, llm).resolve("Heap", [], "")
        assert resolved.course_id == second.course_id


def test_resolve_stage_writes_statements_with_evidence_and_is_repeatable(llm):
    unit = Unit(0, {0: "So we relax the edges here"}, "")
    reply = Extraction.model_validate(
        {
            "concepts": [{"name": "Relaxation"}, {"name": "Dijkstra"}],
            "statements": [
                {
                    "kind": "explanation",
                    "text": "Edges are relaxed",
                    "concepts": ["Relaxation"],
                    "segment_ids": [0],
                    "quote": "relax the edges",
                }
            ],
            "relations": [
                {
                    "source": "Relaxation",
                    "target": "Dijkstra",
                    "type": "PART_OF",
                    "statement_index": 0,
                }
            ],
            "term_fixes": [],
        }
    )
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        add_passage(session, revision, lesson.course_id, "So we relax the edges here")
        from app.models import TranscriptSegment

        session.add(
            TranscriptSegment(
                video_asset_id=revision.video_asset_id,
                seq=0,
                start_ms=1000,
                end_ms=4000,
                text="So we relax the edges here",
            )
        )
        session.add(
            ExtractionUnit(revision_id=revision.id, unit_index=0, result=verify(reply, unit)[0])
        )
        context = context_for(revision, lesson)

    resolve_concepts.run(context)
    resolve_concepts.run(context)

    with session_scope() as session:
        assert session.scalar(select(func.count(Statement.id))) == 1
        assert session.scalar(select(func.count(Concept.id))) == 2
        assert session.scalar(select(func.count(ConceptEdge.id))) == 1
        assert session.scalar(select(func.count(EdgeEvidence.id))) == 1


def test_statements_link_to_concepts_even_when_glm_leaves_their_concepts_empty(llm):
    """Real GLM often omits each statement's concepts; relations and names still link them."""
    line = "Dijkstra's algorithm relaxes each edge once, and relaxing an edge lowers a distance"
    unit = Unit(0, {0: line}, "")
    reply = Extraction.model_validate(
        {
            "concepts": [
                {"name": "Edge relaxation", "aliases": ["relaxing"]},
                {"name": "Dijkstra's algorithm"},
                {"name": "Priority queue"},
            ],
            "statements": [
                {
                    "kind": "explanation",
                    "text": "Dijkstra's algorithm relaxes each edge once.",
                    "segment_ids": [0],
                    "quote": "relaxes each edge once",
                },
                {
                    "kind": "explanation",
                    "text": "Relaxing an edge lowers a distance.",
                    "segment_ids": [0],
                    "quote": "lowers a distance",
                },
            ],
            "relations": [
                {
                    "source": "Edge relaxation",
                    "target": "Dijkstra's algorithm",
                    "type": "PART_OF",
                    "statement_index": 0,
                }
            ],
            "term_fixes": [],
        }
    )
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        add_passage(session, revision, lesson.course_id, line)
        session.add(
            ExtractionUnit(revision_id=revision.id, unit_index=0, result=verify(reply, unit)[0])
        )
        context = context_for(revision, lesson)

    resolve_concepts.run(context)

    with session_scope() as session:
        links = session.execute(
            select(Statement.text, Concept.name)
            .join(StatementConcept, StatementConcept.statement_id == Statement.id)
            .join(Concept, Concept.id == StatementConcept.concept_id)
        ).all()
    assert sorted(links) == [
        ("Dijkstra's algorithm relaxes each edge once.", "Dijkstra's algorithm"),
        ("Dijkstra's algorithm relaxes each edge once.", "Edge relaxation"),
        ("Relaxing an edge lowers a distance.", "Edge relaxation"),
    ]


def test_extraction_prompt_asks_which_concepts_each_statement_is_about():
    from app.knowledge.extraction import SYSTEM

    assert "concepts: the names" in SYSTEM


def test_replacing_a_lesson_hides_its_concepts_and_the_sweep_removes_them():
    with session_scope() as session:
        lesson = make_lesson(session)
        old = make_revision(session, lesson)
        passage = add_passage(session, old, lesson.course_id, "old material about tries")
        statement = add_statement(session, old, lesson.course_id, passage, "tries store prefixes")
        tries = concept(session, lesson.course_id, "Tries")
        link(session, statement, tries)
        vector = fake_vector("tries")

        visible = list(visible_revisions(session, lesson.course_id))
        assert graph_statement_ids(session, lesson.course_id, visible, "tries", vector)

        new = make_revision(session, lesson)
        visible = list(visible_revisions(session, lesson.course_id))
        assert visible == [new.id]
        assert graph_statement_ids(session, lesson.course_id, visible, "tries", vector) == []
        session.delete(session.get(Statement, statement.id))

    runner.sweep_graph()
    with session_scope() as session:
        assert session.scalar(select(func.count(Concept.id))) == 0


def test_graph_pulls_in_what_was_said_about_a_prerequisite_not_in_the_question():
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        course = lesson.course_id
        passage = add_passage(session, revision, course, "calculus review")
        about_backprop = add_statement(session, revision, course, passage, "backprop flows")
        about_chain = add_statement(session, revision, course, passage, "derivatives multiply")
        backprop = concept(session, course, "Backpropagation")
        chain = concept(session, course, "Chain rule")
        link(session, about_backprop, backprop)
        link(session, about_chain, chain)
        edge(session, course, chain, backprop, "PREREQUISITE_OF", about_chain)

        found = graph_statement_ids(
            session,
            course,
            [revision.id],
            "How does backpropagation work?",
            fake_vector("how does backpropagation work"),
        )
        assert about_chain.id in found and found[0] == about_backprop.id


def test_two_hops_only_along_prerequisites():
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        course = lesson.course_id
        passage = add_passage(session, revision, course, "x")
        rows = {}
        for name in ("Alpha", "Bravo", "Charlie", "Delta", "Echo"):
            rows[name] = (
                concept(session, course, name),
                add_statement(session, revision, course, passage, f"about {name}"),
            )
            link(session, rows[name][1], rows[name][0])
        edge(session, course, rows["Bravo"][0], rows["Alpha"][0], "PREREQUISITE_OF",
             rows["Bravo"][1])
        edge(session, course, rows["Charlie"][0], rows["Bravo"][0], "PREREQUISITE_OF",
             rows["Charlie"][1])
        edge(session, course, rows["Delta"][0], rows["Alpha"][0], "RELATED_TO", rows["Delta"][1])
        edge(session, course, rows["Echo"][0], rows["Delta"][0], "RELATED_TO", rows["Echo"][1])

        found = graph_statement_ids(
            session, course, [revision.id], "Alpha", fake_vector("zzz unrelated")
        )
        assert rows["Charlie"][1].id in found
        assert rows["Delta"][1].id in found
        assert rows["Echo"][1].id not in found


def search(session, lesson, question, current_ms=0, preview=None):
    revisions = visible_revisions(session, lesson.course_id, preview)
    return retrieve(
        session, lesson.course_id, lesson, revisions, question, fake_vector(question), current_ms
    )


def test_search_never_crosses_into_another_course():
    with session_scope() as session:
        first = make_lesson(session)
        second = make_lesson(session)
        mine = make_revision(session, first)
        other = make_revision(session, second)
        add_passage(session, mine, first.course_id, "heaps give fast priority queues")
        add_passage(session, other, second.course_id, "heaps give fast priority queues secret")
        results = search(session, first, "heaps priority queues")
        assert results and all(r.lesson_id == first.id for r in results)


def test_unpublished_revision_is_invisible_until_previewed():
    with session_scope() as session:
        lesson = make_lesson(session)
        make_revision(session, lesson)
        draft = make_revision(session, lesson, active=False, status="needs_review")
        add_passage(session, draft, lesson.course_id, "draft words about treaps")
        assert search(session, lesson, "treaps") == []
        assert search(session, lesson, "treaps", preview=draft)[0].text.startswith("draft words")


def test_word_forms_match_through_english_stemming():
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        passage = add_passage(session, revision, lesson.course_id, "relaxing an edge lowers d")
        passage.embedding = None
        session.flush()
        results = search(session, lesson, "why do we relax?")
        assert [r.key for r in results] == [("passage", passage.id)]


def test_exam_hint_outranks_a_plain_statement_with_the_same_words():
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        course = lesson.course_id
        passage = add_passage(session, revision, course, "zzz")
        plain = add_statement(session, revision, course, passage, "dijkstra trace by hand")
        hint = add_statement(session, revision, course, passage, "dijkstra trace by hand",
                             kind="exam_hint")
        ranked = [r.key for r in search(session, lesson, "dijkstra trace by hand")]
        assert ranked.index(("statement", hint.id)) < ranked.index(("statement", plain.id))


def test_playhead_context_is_always_first():
    from tests.conftest import add_slide_timeline

    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        add_slide_timeline(session, revision)
        add_passage(session, revision, lesson.course_id, "unrelated words about heaps")
        results = search(session, lesson, "heaps", current_ms=6000)
        assert results[0].kind == "playhead"
        assert results[0].slide == 1
        assert "relax the edges" in results[0].text


def test_context_budget_is_respected(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("CONTEXT_TOKEN_BUDGET", "50")
    get_settings.cache_clear()
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        for index in range(5):
            add_passage(session, revision, lesson.course_id, f"heaps {index} " + "word " * 40)
        assert len(search(session, lesson, "heaps")) == 1


