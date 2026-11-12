from app.core.db import session_scope
from tests.conftest import add_passage, add_statement, login, make_lesson, make_revision, make_user
from tests.test_knowledge import concept, edge, link

API = "/api/v1"


def graph_course(published=True):
    with session_scope() as session:
        lesson = make_lesson(session, published=published)
        live = make_revision(session, lesson)
        old = make_revision(session, lesson, active=False)
        passage = add_passage(session, live, lesson.course_id, "relax every edge", 754_000)
        statement = add_statement(session, live, lesson.course_id, passage, "Relax every edge.")
        old_passage = add_passage(session, old, lesson.course_id, "old take", 10_000)
        old_statement = add_statement(session, old, lesson.course_id, old_passage, "Old take.")

        relaxation = concept(session, lesson.course_id, "Edge relaxation", ["relaxing"])
        relaxation.summary = "Lower a distance when a shorter path appears."
        bellman = concept(session, lesson.course_id, "Bellman-Ford")
        stale = concept(session, lesson.course_id, "Dropped idea")
        link(session, statement, relaxation)
        link(session, statement, bellman)
        link(session, old_statement, stale)
        edge(session, lesson.course_id, relaxation, bellman, "PART_OF", statement)
        edge(session, lesson.course_id, stale, bellman, "RELATED_TO", old_statement)
        edge(session, lesson.course_id, bellman, relaxation, "USED_FOR", old_statement)
    return lesson


def test_graph_shows_concepts_and_edges_from_published_lessons_only(client):
    lesson = graph_course()
    make_user()
    login(client)
    graph = client.get(f"{API}/courses/{lesson.course_id}/graph").json()

    nodes = {node["name"]: node for node in graph["nodes"]}
    assert set(nodes) == {"Edge relaxation", "Bellman-Ford"}
    relaxation = nodes["Edge relaxation"]
    assert relaxation["aliases"] == ["relaxing"]
    assert relaxation["summary"].startswith("Lower a distance")
    assert relaxation["moments"] == [
        {
            "lesson_id": lesson.id,
            "lesson_title": "Shortest paths",
            "lesson_position": 1,
            "start_ms": 754_000,
            "text": "Relax every edge.",
        }
    ]
    assert graph["edges"] == [
        {"source": relaxation["id"], "target": nodes["Bellman-Ford"]["id"], "type": "PART_OF"}
    ]


def test_students_cannot_see_the_graph_of_a_draft_course(client):
    lesson = graph_course(published=False)
    make_user()
    login(client)
    assert client.get(f"{API}/courses/{lesson.course_id}/graph").status_code == 404
