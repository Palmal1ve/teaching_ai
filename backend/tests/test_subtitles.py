from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.db import session_scope
from app.models import TranscriptAsset, TranscriptSegment, VideoAsset
from app.pipeline.context import StageContext
from app.pipeline.errors import PermanentError
from app.pipeline.stages import transcribe
from app.pipeline.subtitles import decode, parse
from tests.conftest import make_lesson

SRT = (
    "﻿1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>Dijkstra</i> relaxes\r\nevery edge\r\n\r\n"
    "2\r\n00:00:03,000 --> 00:00:04,000\r\nTom &amp; Jerry\r\n"
).encode()

VTT = b"""WEBVTT

NOTE written by hand

00:01.000 --> 00:02.000 align:start
<v Prof>Shortest paths</v>

1:00:00.000 --> 1:00:01.250
An hour in
"""


def test_srt_lines_lose_tags_and_join_wrapped_rows():
    assert parse(decode(SRT)) == [
        (1000, 2500, "Dijkstra relaxes every edge"),
        (3000, 4000, "Tom & Jerry"),
    ]


def test_vtt_skips_header_and_notes_and_reads_short_times():
    assert parse(decode(VTT)) == [
        (1000, 2000, "Shortest paths"),
        (3_600_000, 3_601_250, "An hour in"),
    ]


def test_text_without_times_gives_no_lines():
    assert parse("just some words") == []


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"00:00:02,000 --> 00:00:01,000\nback", "line 1 ends before"),
        (b"00:00:05,000 --> 00:00:06,000\na\n\n00:00:01,000 --> 00:00:02,000\nb", "line 2 starts"),
        ("00:00:01,000 --> 00:00:02,000\n讲".encode("gbk"), "UTF-8"),
    ],
)
def test_bad_files_fail_with_a_reason(data, message):
    with pytest.raises(PermanentError, match=message):
        parse(decode(data))


PDF_TEXT = """Lecture 4: Shortest paths\f
00:00:05 Professor: Today we cover
Dijkstra's algorithm.
[00:00:09] Student: Why relax?
00:00:09 Professor: Good question.
Speaker 2   1:02:03
An hour later
"""


def test_pdf_text_with_leading_and_trailing_times_runs_until_the_next_line():
    assert parse(PDF_TEXT) == [
        (5000, 9000, "Professor: Today we cover Dijkstra's algorithm."),
        (9000, 3_723_000, "Student: Why relax? Professor: Good question."),
        (3_723_000, 3_733_000, "An hour later"),
    ]


def test_srt_saved_as_pdf_loses_its_blank_lines_and_still_reads():
    text = "1\n00:00:01,000 --> 00:00:02,000\nfirst\n2\n00:00:03,000 --> 00:00:04,000\nsecond\n"
    assert parse(text) == [(1000, 2000, "first"), (3000, 4000, "second")]


def test_pdf_transcript_is_read_with_pdftotext(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        "app.pipeline.media.get_settings", lambda: SimpleNamespace(work_dir=tmp_path)
    )
    monkeypatch.setattr("app.core.storage.download", lambda key, path: path)
    monkeypatch.setattr(transcribe, "sh", lambda cmd: commands.append(cmd) or "00:01 hi")
    assert transcribe._from_upload("uploads/1/source.pdf", None, None) == [(1000, 11_000, "hi")]
    assert commands[0][0] == "pdftotext"


def test_uploaded_transcript_replaces_whisper_and_stops_at_the_video_end(monkeypatch):
    data = (
        b"00:00:01,000 --> 00:00:02,000\nin\n\n"
        b"00:00:09,000 --> 00:00:12,000\ncut\n\n"
        b"00:00:10,000 --> 00:00:11,000\nafter"
    )
    monkeypatch.setattr("app.core.storage.read_bytes", lambda key: data)
    monkeypatch.setattr(transcribe, "_model", lambda: pytest.fail("Whisper must not run"))
    with session_scope() as session:
        lesson = make_lesson(session)
        transcript = TranscriptAsset(lesson_id=lesson.id, storage_key="t", filename="a.srt")
        session.add(transcript)
        session.flush()
        video = VideoAsset(
            lesson_id=lesson.id,
            storage_key="v",
            duration_ms=10_000,
            transcript_asset_id=transcript.id,
        )
        session.add(video)
        session.flush()
        context = StageContext(1, lesson.id, lesson.course_id, video.id, None)
    transcribe.run(context)
    with session_scope() as session:
        rows = session.scalars(select(TranscriptSegment).order_by(TranscriptSegment.seq)).all()
        assert [(r.start_ms, r.end_ms, r.text) for r in rows] == [
            (1000, 2000, "in"),
            (9000, 10_000, "cut"),
        ]
        assert session.get(VideoAsset, video.id).transcribed_at is not None
