import json

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.embeddings import EmbedderUnavailable
from app.models import (
    ChatMessage,
    Concept,
    Course,
    Lesson,
    LessonRevision,
    LLMUsage,
    Passage,
    PipelineStage,
    Slide,
    SlideInterval,
    StatementConcept,
    TranscriptSegment,
    VideoAsset,
)
from tests.conftest import (
    add_passage,
    add_slide_timeline,
    add_statement,
    fake_vector,
    login,
    make_lesson,
    make_revision,
    make_user,
)

API = "/api/v1"


def published_lesson():
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        add_slide_timeline(session, revision)
        add_passage(
            session,
            revision,
            lesson.course_id,
            "we relax the edges because a shorter path might appear",
            754_000,
            790_000,
        )
    return lesson.id, revision.id


def chat(client, lesson_id):
    return client.post(f"{API}/lessons/{lesson_id}/chat/sessions").json()["id"]


def ask(client, session_id, text="Why relax edges?", ms=1000, **extra):
    return client.post(
        f"{API}/chat/sessions/{session_id}/messages",
        json={"text": text, "current_time_ms": ms, **extra},
    )


def test_every_route_needs_a_login(client):
    assert client.get(f"{API}/courses").status_code == 401
    assert client.get(f"{API}/auth/me").status_code == 401


def test_login_sets_an_httponly_cookie_and_logout_clears_it(client):
    make_user()
    response = client.post(
        f"{API}/auth/login", json={"email": "student@x.edu", "password": "pw"}
    )
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.get(f"{API}/auth/me").json()["role"] == "student"
    client.post(f"{API}/auth/logout")
    assert client.get(f"{API}/auth/me").status_code == 401


def test_wrong_password_is_refused(client):
    make_user()
    response = client.post(f"{API}/auth/login", json={"email": "student@x.edu", "password": "no"})
    assert response.status_code == 401


def test_demo_login_is_off_unless_enabled(client):
    assert client.get(f"{API}/auth/demo").json() == {"enabled": False}
    assert client.post(f"{API}/auth/demo/student").status_code == 404


def test_demo_login_signs_in_as_student_or_admin(client, monkeypatch):
    monkeypatch.setenv("DEMO_LOGIN", "1")
    get_settings.cache_clear()
    assert client.get(f"{API}/auth/demo").json() == {"enabled": True}
    assert client.post(f"{API}/auth/demo/student").json()["role"] == "student"
    assert client.get(f"{API}/auth/me").json()["role"] == "student"
    assert client.post(f"{API}/auth/demo/admin").json()["role"] == "admin"
    assert client.get(f"{API}/admin/courses").status_code == 200
    assert client.post(f"{API}/auth/demo/admin").status_code == 200
    assert client.post(f"{API}/auth/demo/root").status_code == 422


def test_students_cannot_reach_admin_routes(client):
    make_user()
    login(client)
    assert client.get(f"{API}/admin/courses").status_code == 403


def test_students_see_published_courses_and_published_lessons_only(client):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    with session_scope() as session:
        course_id = session.get(Lesson, lesson_id).course_id
        session.add(Lesson(course_id=course_id, position=2, title="Unfinished"))
        session.add(Course(title="Secret draft"))
    assert [c["title"] for c in client.get(f"{API}/courses").json()] == ["Algorithms"]
    lessons = client.get(f"{API}/courses/{course_id}").json()["lessons"]
    assert [lesson["id"] for lesson in lessons] == [lesson_id]


def test_course_lessons_carry_length_and_concept_count(client):
    make_user()
    login(client)
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson)
        passage = add_passage(session, revision, lesson.course_id, "relax every edge")
        statement = add_statement(session, revision, lesson.course_id, passage, "relax every edge")
        for name in ("Edge relaxation", "Bellman-Ford"):
            concept = Concept(course_id=lesson.course_id, name=name, embedding=fake_vector(name))
            session.add(concept)
            session.flush()
            session.add(StatementConcept(statement_id=statement.id, concept_id=concept.id))
        course_id = lesson.course_id
    [row] = client.get(f"{API}/courses/{course_id}").json()["lessons"]
    assert row["duration_ms"] == 600_000
    assert row["concept_count"] == 2


def test_player_returns_everything_in_one_call(client):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    data = client.get(f"{API}/lessons/{lesson_id}/player").json()
    assert data["hls_url"].endswith("/hls/master.m3u8")
    assert data["transcript"][0]["text"] == "So we relax the edges here"
    assert [s["number"] for s in data["slides"]] == [1, 2]
    assert data["timeline"][0] == {
        "start_ms": 0, "end_ms": 300_000, "slide": 1, "estimated": False,
    }
    assert data["timeline"][1]["estimated"] is True


def test_student_cannot_open_a_draft_revision(client):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    with session_scope() as session:
        draft = make_revision(
            session, session.get(Lesson, lesson_id), active=False, status="needs_review"
        )
    url = f"{API}/lessons/{lesson_id}/player?revision_id={draft.id}"
    assert client.get(url).json()["revision_id"] != draft.id


def test_admin_can_review_a_draft_as_a_student_would(client):
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    with session_scope() as session:
        lesson = make_lesson(session)
        draft = make_revision(session, lesson, active=False, status="needs_review")
    response = client.get(f"{API}/lessons/{lesson.id}/player?revision_id={draft.id}")
    assert response.json()["revision_id"] == draft.id


def test_chat_returns_a_checked_answer_that_jumps_to_the_moment(client, llm):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    llm.reply = "We relax the edges because a shorter path might appear [S2]."
    response = ask(client, chat(client, lesson_id), "why relax the edges?")
    assert response.status_code == 200
    body = response.json()
    assert body["grounding"] == "grounded"
    assert body["citations"][0]["start_ms"] == 754_000
    assert body["citations"][0]["lesson_id"] == lesson_id
    assert "[1]" in body["text"] and "[S" not in body["text"]


def test_prompt_contains_course_text_but_no_student_details(client, llm):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    ask(client, chat(client, lesson_id))
    sent = str(llm.messages)
    assert "relax the edges" in sent
    assert "student@x.edu" not in sent


def test_chat_history_keeps_citations_after_reprocessing(client, llm):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    session_id = chat(client, lesson_id)
    llm.reply = "We relax the edges because a shorter path might appear [S2]."
    ask(client, session_id, "why relax the edges?")
    with session_scope() as session:
        session.execute(Passage.__table__.delete())
    messages = client.get(f"{API}/chat/sessions/{session_id}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations"][0]["start_ms"] == 754_000


def test_follow_up_searches_with_the_previous_question(client, llm):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    session_id = chat(client, lesson_id)
    llm.reply = "Earlier answer [S1]."
    ask(client, session_id, "why relax the edges?", ms=0)
    ask(client, session_id, "and the second one?", ms=0)
    roles = [m["role"] for m in llm.messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert "shorter path" in llm.messages[-1]["content"]
    assert "[1]" not in llm.messages[2]["content"]


def test_glm_down_gives_assistant_offline_and_keeps_no_partial_message(client, llm):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    session_id = chat(client, lesson_id)
    llm.down = True
    response = ask(client, session_id)
    assert response.status_code == 503
    assert response.json() == {"code": "assistant_offline"}
    with session_scope() as session:
        assert session.scalars(select(ChatMessage)).first() is None
    assert client.get(f"{API}/lessons/{lesson_id}/player").status_code == 200


def test_embedder_down_is_also_offline(client, monkeypatch):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    session_id = chat(client, lesson_id)

    def broken(texts):
        raise EmbedderUnavailable("ConnectError")

    monkeypatch.setattr("app.assistant.answer.embed", broken)
    assert ask(client, session_id).status_code == 503


def test_daily_question_limit_and_outages_do_not_use_it_up(client, llm, monkeypatch):
    monkeypatch.setenv("QUESTIONS_PER_DAY", "2")
    from app.core.config import get_settings

    get_settings.cache_clear()
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    session_id = chat(client, lesson_id)
    llm.down = True
    assert ask(client, session_id).status_code == 503
    llm.down = False
    assert ask(client, session_id).status_code == 200
    assert ask(client, session_id).status_code == 200
    assert ask(client, session_id).status_code == 429


def test_usage_is_recorded_without_the_question_text(client, llm):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    ask(client, chat(client, lesson_id))
    with session_scope() as session:
        usage = session.scalars(select(LLMUsage)).one()
        assert usage.purpose == "chat" and usage.lesson_id == lesson_id


def test_another_students_chat_is_not_found(client):
    make_user()
    make_user("other@x.edu")
    login(client)
    lesson_id, _ = published_lesson()
    session_id = chat(client, lesson_id)
    client.post(f"{API}/auth/logout")
    login(client, "other@x.edu")
    assert client.get(f"{API}/chat/sessions/{session_id}/messages").status_code == 404
    assert ask(client, session_id).status_code == 404


def test_student_cannot_preview_a_draft_through_chat(client):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    with session_scope() as session:
        draft = make_revision(
            session, session.get(Lesson, lesson_id), active=False, status="needs_review"
        )
    assert ask(client, chat(client, lesson_id), revision_id=draft.id).status_code == 404


def media(client, path):
    return client.get(f"{API}/internal/media-auth", headers={"X-Original-URI": path})


def test_media_needs_a_login(client):
    assert media(client, "/media/videos/1/hls/master.m3u8").status_code == 401


def test_student_can_stream_published_media_only(client):
    make_user()
    login(client)
    lesson_id, _ = published_lesson()
    with session_scope() as session:
        revision = session.scalars(select(LessonRevision)).first()
        video, deck = revision.video_asset_id, revision.deck_asset_id
        draft_lesson = make_lesson(session, session.get(Lesson, lesson_id).course_id, 2)
        draft = make_revision(session, draft_lesson, active=False, status="needs_review")
        draft_video = draft.video_asset_id
    assert media(client, f"/media/videos/{video}/hls/master.m3u8").status_code == 204
    assert media(client, f"/media/decks/{deck}/slides/0001.png").status_code == 204
    assert media(client, f"/media/videos/{draft_video}/hls/master.m3u8").status_code == 403
    assert media(client, f"/media/videos/{video}/shots/00000.jpg").status_code == 403


def test_original_uploads_are_never_served(client):
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    assert media(client, "/media/uploads/1/source.mp4").status_code == 401
    assert media(client, "/media/videos/1/audio.flac").status_code == 401


def admin_with_review():
    make_user("admin@x.edu", "admin")
    with session_scope() as session:
        lesson = make_lesson(session)
        revision = make_revision(session, lesson, active=False, status="needs_review")
        add_slide_timeline(session, revision)
        add_passage(session, revision, lesson.course_id, "words", 100_000, 200_000)
    return lesson.id, revision.id


def test_timeline_correction_saves_manual_rows_and_relinks_passages(client):
    _, revision = admin_with_review()
    login(client, "admin@x.edu")
    url = f"{API}/admin/revisions/{revision}/timeline"
    rows = client.get(url).json()["rows"]
    assert len(rows) == 2
    rows[0]["end_ms"] = 60_000
    rows[1]["start_ms"] = 60_000
    assert client.put(url, json={"rows": rows}).status_code == 204
    with session_scope() as session:
        saved = session.scalars(select(SlideInterval).order_by(SlideInterval.start_ms)).all()
        assert [r.source for r in saved] == ["manual", "manual"]
        passage = session.scalars(select(Passage)).one()
        slide = session.get(Slide, passage.slide_id)
        assert slide.number == 2


def test_timeline_with_a_gap_is_refused(client):
    _, revision = admin_with_review()
    login(client, "admin@x.edu")
    url = f"{API}/admin/revisions/{revision}/timeline"
    rows = client.get(url).json()["rows"]
    rows[1]["start_ms"] = 310_000
    assert client.put(url, json={"rows": rows}).status_code == 422


def test_timeline_must_reach_the_end_of_the_video(client):
    _, revision = admin_with_review()
    login(client, "admin@x.edu")
    url = f"{API}/admin/revisions/{revision}/timeline"
    rows = client.get(url).json()["rows"]
    rows[1]["end_ms"] = 500_000
    assert client.put(url, json={"rows": rows}).status_code == 422


def test_unchanged_rows_keep_their_automatic_label(client):
    _, revision = admin_with_review()
    login(client, "admin@x.edu")
    url = f"{API}/admin/revisions/{revision}/timeline"
    rows = client.get(url).json()["rows"]
    client.put(url, json={"rows": rows})
    with session_scope() as session:
        assert {r.source for r in session.scalars(select(SlideInterval))} == {"auto"}


def test_transcript_edit_changes_display_never_timestamps(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.admin.reembed_passages.delay", calls.append)
    _, revision = admin_with_review()
    login(client, "admin@x.edu")
    with session_scope() as session:
        segment = session.scalars(select(TranscriptSegment)).one()
        passage = session.scalars(select(Passage)).one()
        passage.first_seq = passage.last_seq = segment.seq
    response = client.patch(f"{API}/admin/segments/{segment.id}", json={"text": "Dijkstra relaxes"})
    assert response.json()["text"] == "Dijkstra relaxes"
    assert response.json()["start_ms"] == 1000
    with session_scope() as session:
        stored = session.get(TranscriptSegment, segment.id)
        assert stored.text == "So we relax the edges here" and stored.admin_edited
        passage = session.scalars(select(Passage)).one()
        assert passage.text == "Dijkstra relaxes" and passage.embedding is None
    assert calls == [revision]


def test_publish_flips_the_active_revision_and_can_be_reversed(client):
    lesson_id, draft = admin_with_review()
    login(client, "admin@x.edu")
    assert client.post(f"{API}/admin/revisions/{draft}/publish").status_code == 200
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        assert lesson.active_revision_id == draft and lesson.status == "published"
        newer = make_revision(session, lesson, active=False, status="needs_review")
    client.post(f"{API}/admin/revisions/{newer.id}/publish")
    client.post(f"{API}/admin/revisions/{draft}/publish")
    with session_scope() as session:
        assert session.get(Lesson, lesson_id).active_revision_id == draft


def test_unfinished_revision_cannot_be_published(client):
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    with session_scope() as session:
        revision = make_revision(
            session, make_lesson(session), active=False, status="processing"
        )
    assert client.post(f"{API}/admin/revisions/{revision.id}/publish").status_code == 409


def test_admin_course_and_lesson_crud(client):
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    course = client.post(f"{API}/admin/courses", json={"title": "Graphs"}).json()
    assert course["status"] == "draft"
    first = client.post(
        f"{API}/admin/lessons", json={"course_id": course["id"], "title": "Intro"}
    ).json()
    second = client.post(
        f"{API}/admin/lessons", json={"course_id": course["id"], "title": "Next"}
    ).json()
    assert (first["position"], second["position"]) == (1, 2)
    client.patch(f"{API}/admin/courses/{course['id']}", json={"status": "published"})
    assert client.get(f"{API}/courses").json()[0]["status"] == "published"
    assert client.delete(f"{API}/admin/lessons/{first['id']}").status_code == 204
    assert client.delete(f"{API}/admin/courses/{course['id']}").status_code == 204
    assert client.get(f"{API}/admin/courses").json() == []


def test_wrong_upload_type_and_size_are_refused(client):
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    with session_scope() as session:
        lesson = make_lesson(session)
    url = f"{API}/admin/lessons/{lesson.id}/uploads"
    bad_type = {"kind": "video", "filename": "evil.exe", "size": 10}
    too_big = {"kind": "video", "filename": "a.mp4", "size": 11 * 1024**3}
    assert client.post(url, json=bad_type).status_code == 422
    assert client.post(url, json=too_big).status_code == 413


def test_progress_stream_sends_the_stages_and_ends_when_published(client):
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    with session_scope() as session:
        revision = make_revision(session, make_lesson(session))
        session.add(PipelineStage(revision_id=revision.id, name="probe", status="done"))
    with client.stream("GET", f"{API}/admin/revisions/{revision.id}/events") as stream:
        lines = [line for line in stream.iter_lines() if line]
    assert stream.headers["content-type"].startswith("text/event-stream")
    data = json.loads(lines[0].removeprefix("data: "))
    assert data["status"] == "published"
    assert data["stages"][0]["name"] == "probe"


class FakeS3:
    def __init__(self):
        self.aborted = []

    def create_multipart_upload(self, Bucket, Key):
        return {"UploadId": f"s3-{Key}"}

    def generate_presigned_url(self, *args, **kwargs):
        return "http://minio:9000/signed"

    def list_parts(self, **kwargs):
        return {"Parts": [{"PartNumber": 1, "ETag": "x", "Size": 5}]}

    def complete_multipart_upload(self, **kwargs):
        pass

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append(Key)


def uploads(client, monkeypatch, enqueued):
    s3 = FakeS3()
    monkeypatch.setattr("app.core.storage.client", lambda: s3)
    make_user("admin@x.edu", "admin")
    login(client, "admin@x.edu")
    with session_scope() as session:
        lesson = make_lesson(session)

    def start(kind, name):
        return client.post(
            f"{API}/admin/lessons/{lesson.id}/uploads",
            json={"kind": kind, "filename": name, "size": 10},
        ).json()["upload_id"]

    return s3, start


def complete(client, upload_id):
    assert client.post(f"{API}/admin/uploads/{upload_id}/complete").status_code == 204


def save(client, lesson_id=1):
    return client.post(f"{API}/admin/lessons/{lesson_id}/save")


def saved(client, *upload_ids):
    for upload_id in upload_ids:
        complete(client, upload_id)
    response = save(client)
    assert response.status_code == 200
    return response.json()["revision_id"]


def revision_count():
    with session_scope() as session:
        return len(session.scalars(select(LessonRevision)).all())


def test_part_urls_go_through_nginx_not_straight_to_storage(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    status_url = f"{API}/admin/uploads/{start('video', 'a.mp4')}"
    assert client.get(status_url).json()["parts"][0]["url"] == "/s3/signed"


def test_finished_uploads_wait_for_save_then_start_one_revision(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    complete(client, start("deck", "a.pptx"))
    complete(client, start("video", "a.mp4"))
    assert revision_count() == 0
    unsaved = client.get(f"{API}/admin/lessons/1").json()["unsaved"]
    assert unsaved == [
        {"kind": "video", "filename": "a.mp4"},
        {"kind": "deck", "filename": "a.pptx"},
    ]
    assert save(client).json()["revision_id"] is not None
    assert revision_count() == 1
    assert client.get(f"{API}/admin/lessons/1").json()["unsaved"] == []


def test_save_needs_a_video_and_something_new(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    complete(client, start("deck", "a.pptx"))
    assert save(client).json()["detail"] == "Upload a video first"
    saved(client, start("video", "a.mp4"))
    assert save(client).json()["detail"] == "Nothing new to save"


def test_save_closes_an_upload_left_by_a_closed_tab(client, monkeypatch, enqueued):
    s3, start = uploads(client, monkeypatch, enqueued)
    abandoned = start("deck", "half.pptx")
    saved(client, start("video", "a.mp4"))
    assert s3.aborted == [f"uploads/{abandoned}/source.pptx"]


def test_a_closed_tab_does_not_block_the_next_attempt(client, monkeypatch, enqueued):
    s3, start = uploads(client, monkeypatch, enqueued)
    start("video", "abandoned.mp4")
    assert saved(client, start("video", "again.mp4")) is not None
    assert len(s3.aborted) == 1


def test_cancelling_an_upload_starts_nothing(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    complete(client, start("video", "a.mp4"))
    assert client.delete(f"{API}/admin/uploads/{start('deck', 'a.pptx')}").status_code == 204
    assert revision_count() == 0


def test_completing_twice_is_refused(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    upload = start("video", "a.mp4")
    complete(client, upload)
    response = client.post(f"{API}/admin/uploads/{upload}/complete")
    assert response.status_code == 409


def test_transcript_is_a_supported_upload_and_others_are_not(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    assert start("transcript", "a.srt")
    url = f"{API}/admin/lessons/1/uploads"
    bad = {"kind": "transcript", "filename": "a.txt", "size": 10}
    big = {"kind": "transcript", "filename": "a.vtt", "size": 21 * 1024**2}
    assert client.post(url, json=bad).status_code == 422
    assert client.post(url, json=big).status_code == 413


def test_video_deck_and_transcript_saved_together_start_one_revision(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    saved(client, start("transcript", "a.srt"), start("video", "a.mp4"), start("deck", "a.pptx"))
    with session_scope() as session:
        revision = session.scalars(select(LessonRevision)).one()
        video = session.get(VideoAsset, revision.video_asset_id)
        assert video.transcript_asset_id is not None
        stage = session.scalars(
            select(PipelineStage).where(PipelineStage.name == "extract_audio")
        ).one()
        assert stage.status == "skipped"
    lesson = client.get(f"{API}/admin/lessons/{revision.lesson_id}").json()
    assert lesson["revisions"][0]["transcript_file"] == "a.srt"


def test_new_transcript_leaves_the_live_lines_until_publish(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    live = saved(client, start("video", "a.mp4"))
    with session_scope() as session:
        live_video = session.get(LessonRevision, live).video_asset_id
        video = session.get(VideoAsset, live_video)
        video.hls_key, video.duration_ms = f"videos/{live_video}/hls/master.m3u8", 600_000
        session.add(
            TranscriptSegment(video_asset_id=live_video, seq=0, start_ms=0, end_ms=1, text="old")
        )
        session.get(LessonRevision, live).status = "needs_review"
    client.post(f"{API}/admin/revisions/{live}/publish")

    draft = saved(client, start("transcript", "fixed.vtt"))
    with session_scope() as session:
        copy = session.get(VideoAsset, session.get(LessonRevision, draft).video_asset_id)
        assert copy.id != live_video and copy.hls_key == f"videos/{live_video}/hls/master.m3u8"
        assert session.get(LessonRevision, live).status == "published"
        assert session.scalars(select(TranscriptSegment.text)).all() == ["old"]
        session.get(Course, 1).status = "published"
        session.get(LessonRevision, draft).status = "needs_review"
    client.post(f"{API}/admin/revisions/{draft}/publish")

    make_user()
    login(client)
    assert media(client, f"/media/videos/{live_video}/hls/master.m3u8").status_code == 204


def test_new_video_without_a_transcript_uses_whisper(client, monkeypatch, enqueued):
    _, start = uploads(client, monkeypatch, enqueued)
    saved(client, start("transcript", "a.srt"), start("video", "a.mp4"))
    second = saved(client, start("video", "b.mp4"))
    with session_scope() as session:
        video = session.get(VideoAsset, session.get(LessonRevision, second).video_asset_id)
        assert video.transcript_asset_id is None
