from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import session_scope
from app.core.llm import LLMUnavailable
from app.models import LessonRevision, PipelineStage
from app.pipeline import runner
from app.pipeline.errors import PermanentError
from app.pipeline.graph import DECK_ONLY, STAGES
from app.pipeline.revisions import create_revision
from tests.conftest import make_lesson, make_revision


def start(with_deck=True, produced=False):
    with session_scope() as session:
        lesson = make_lesson(session)
        base = make_revision(session, lesson, with_deck, active=False, status="superseded")
        video = session.get(__import__("app.models").models.VideoAsset, base.video_asset_id)
        deck_model = __import__("app.models").models.DeckAsset
        deck = session.get(deck_model, base.deck_asset_id) if with_deck else None
        if not produced:
            video.hls_key = None
            video.duration_ms = None
            if deck:
                deck.slide_count = None
        revision = create_revision(session, lesson, video, deck)
    return revision.id


def stages(revision_id):
    with session_scope() as session:
        rows = session.scalars(
            select(PipelineStage).where(PipelineStage.revision_id == revision_id)
        )
        return {s.name: s.status for s in rows}


def stage_id(revision_id, name):
    with session_scope() as session:
        return session.scalars(
            select(PipelineStage.id).where(
                PipelineStage.revision_id == revision_id, PipelineStage.name == name
            )
        ).one()


def finish(revision_id, name):
    runner._finish(stage_id(revision_id, name))
    runner.advance(revision_id)


def fake_stage(monkeypatch, raises=None):
    class Module:
        @staticmethod
        def run(context):
            if raises:
                raise raises

    monkeypatch.setattr(runner.importlib, "import_module", lambda name: Module)


def queue(revision_id, name):
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id(revision_id, name))
        stage.status = "queued"


def test_first_advance_starts_only_stages_with_no_dependencies(enqueued):
    revision = start()
    runner.advance(revision)
    assert sorted(enqueued) == ["probe", "render_deck"]


def test_probe_unblocks_its_three_children_but_not_transcribe(enqueued):
    revision = start()
    runner.advance(revision)
    finish(revision, "probe")
    assert {"transcode_hls", "extract_audio", "sample_frames"} <= set(enqueued)
    assert "transcribe" not in enqueued


def test_transcribe_waits_for_the_deck_vocabulary(enqueued):
    revision = start()
    runner.advance(revision)
    finish(revision, "probe")
    finish(revision, "extract_audio")
    assert "transcribe" not in enqueued
    finish(revision, "render_deck")
    assert "transcribe" in enqueued


def test_no_deck_skips_deck_stages_and_passages_follow_transcribe(enqueued):
    revision = start(with_deck=False)
    status = stages(revision)
    assert {status[name] for name in DECK_ONLY} == {"skipped"}
    runner.advance(revision)
    finish(revision, "probe")
    finish(revision, "extract_audio")
    finish(revision, "transcribe")
    assert "build_passages" in enqueued


def test_new_deck_on_a_processed_video_reuses_video_stages(enqueued):
    with session_scope() as session:
        lesson = make_lesson(session)
        base = make_revision(session, lesson, False, active=False, status="superseded")
        from datetime import UTC, datetime

        from app.models import DeckAsset, VideoAsset

        video = session.get(VideoAsset, base.video_asset_id)
        video.audio_key = "a"
        video.shots_key = "s"
        video.transcribed_at = datetime.now(UTC)
        deck = DeckAsset(lesson_id=lesson.id, storage_key="k", filename="d.pdf")
        session.add(deck)
        session.flush()
        revision_id = create_revision(session, lesson, video, deck).id
    status = stages(revision_id)
    for name in ("probe", "transcode_hls", "extract_audio", "transcribe", "sample_frames"):
        assert status[name] == "skipped"
    assert status["render_deck"] == "pending"
    assert status["build_passages"] == "pending"


def test_all_stages_done_moves_to_needs_review(enqueued):
    revision = start(with_deck=False)
    runner.advance(revision)
    for name in STAGES:
        if stages(revision)[name] != "skipped":
            finish(revision, name)
    with session_scope() as session:
        assert session.get(LessonRevision, revision).status == "needs_review"


def test_failure_retries_with_backoff_then_stops(enqueued, monkeypatch):
    revision = start()
    fake_stage(monkeypatch, RuntimeError("boom"))
    sid = stage_id(revision, "probe")
    for attempt in range(1, 4):
        queue(revision, "probe")
        runner.run_stage(sid)
        with session_scope() as session:
            assert session.get(PipelineStage, sid).attempts == attempt
    assert stages(revision)["probe"] == "failed"
    with session_scope() as session:
        assert session.get(LessonRevision, revision).status == "failed"


def test_bad_input_fails_at_once_with_the_reason(enqueued, monkeypatch):
    revision = start()
    fake_stage(monkeypatch, PermanentError("This video has no audio"))
    queue(revision, "probe")
    runner.run_stage(stage_id(revision, "probe"))
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id(revision, "probe"))
        assert stage.status == "failed" and stage.attempts == 1
        assert stage.error == "This video has no audio"


def test_glm_outage_waits_instead_of_failing(enqueued, monkeypatch):
    revision = start()
    fake_stage(monkeypatch, LLMUnavailable("ConnectError"))
    queue(revision, "extract_knowledge")
    sid = stage_id(revision, "extract_knowledge")
    runner.run_stage(sid)
    with session_scope() as session:
        stage = session.get(PipelineStage, sid)
        assert stage.status == "waiting_for_llm"
        assert stage.attempts == 0
        stage.retry_at = runner.now() - timedelta(seconds=1)
        session.get(PipelineStage, stage_id(revision, "build_passages")).status = "done"
    runner.sweep()
    assert stages(revision)["extract_knowledge"] == "queued"


def test_crashed_worker_is_detected_by_stale_heartbeat(enqueued):
    revision = start()
    sid = stage_id(revision, "probe")
    with session_scope() as session:
        stage = session.get(PipelineStage, sid)
        stage.status = "running"
        stage.heartbeat_at = runner.now() - timedelta(minutes=10)
    runner.sweep()
    assert stages(revision)["probe"] == "queued"
    assert "probe" in enqueued


def test_healthy_long_stage_is_left_alone(enqueued):
    revision = start()
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id(revision, "probe"))
        stage.status = "running"
        stage.started_at = runner.now() - timedelta(hours=2)
        stage.heartbeat_at = runner.now()
    runner.sweep()
    assert stages(revision)["probe"] == "running"


def test_lost_queue_message_is_sent_again(enqueued):
    revision = start()
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id(revision, "probe"))
        stage.status = "queued"
        stage.queued_at = runner.now() - timedelta(hours=1)
    runner.sweep()
    assert enqueued == ["probe"]


def test_duplicate_delivery_runs_a_stage_once(enqueued, monkeypatch):
    revision = start()
    calls = []

    class Module:
        @staticmethod
        def run(context):
            calls.append(1)

    monkeypatch.setattr(runner.importlib, "import_module", lambda name: Module)
    queue(revision, "probe")
    sid = stage_id(revision, "probe")
    runner.run_stage(sid)
    runner.run_stage(sid)
    assert len(calls) == 1


def test_new_upload_cancels_the_old_unfinished_revision(enqueued):
    revision = start()
    runner.advance(revision)
    with session_scope() as session:
        old = session.get(LessonRevision, revision)
        lesson = session.get(__import__("app.models").models.Lesson, old.lesson_id)
        video = session.get(__import__("app.models").models.VideoAsset, old.video_asset_id)
        create_revision(session, lesson, video, None)
    with session_scope() as session:
        assert session.get(LessonRevision, revision).status == "superseded"
    assert "cancelled" in stages(revision).values()
    runner.run_stage(stage_id(revision, "probe"))
    assert stages(revision)["probe"] == "cancelled"


@pytest.mark.parametrize("name", list(STAGES))
def test_every_dependency_is_a_real_stage(name):
    assert all(dep in STAGES for dep in STAGES[name][1])


def test_uploaded_transcript_skips_audio_and_still_waits_for_probe(enqueued):
    from app.models import TranscriptAsset, VideoAsset

    with session_scope() as session:
        lesson = make_lesson(session)
        transcript = TranscriptAsset(lesson_id=lesson.id, storage_key="t", filename="a.vtt")
        session.add(transcript)
        session.flush()
        video = VideoAsset(lesson_id=lesson.id, storage_key="v", transcript_asset_id=transcript.id)
        session.add(video)
        session.flush()
        revision = create_revision(session, lesson, video, None).id
    assert stages(revision)["extract_audio"] == "skipped"
    runner.advance(revision)
    assert "transcribe" not in enqueued
    finish(revision, "probe")
    assert "transcribe" in enqueued


def test_pdf_transcript_keeps_the_audio_in_case_it_has_no_times(enqueued):
    from app.models import TranscriptAsset, VideoAsset

    with session_scope() as session:
        lesson = make_lesson(session)
        transcript = TranscriptAsset(
            lesson_id=lesson.id, storage_key="uploads/1/source.pdf", filename="a.pdf"
        )
        session.add(transcript)
        session.flush()
        video = VideoAsset(lesson_id=lesson.id, storage_key="v", transcript_asset_id=transcript.id)
        session.add(video)
        session.flush()
        revision = create_revision(session, lesson, video, None).id
    assert stages(revision)["extract_audio"] == "pending"
