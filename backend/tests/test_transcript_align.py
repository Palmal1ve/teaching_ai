from types import SimpleNamespace

import pytest

from app.pipeline.errors import PermanentError
from app.pipeline.stages import transcribe
from app.pipeline.transcript_align import MAX_TOKENS, align, sentences


def heard(text, step=500):
    return [(word, i * step, i * step + 400) for i, word in enumerate(text.split())]


def test_sentences_split_at_full_stops_in_english_and_chinese():
    assert sentences("We relax edges.  Why?\nBecause it works") == [
        "We relax edges.",
        "Why?",
        "Because it works",
    ]
    assert sentences("我们放松边。为什么？") == ["我们放松边。", "为什么？"]


def test_long_sentences_break_at_commas():
    clause = " ".join(["word"] * 30)
    lines = sentences(f"{clause}, {clause}, {clause}.")
    assert len(lines) == 3
    assert all(len(line.split()) <= MAX_TOKENS for line in lines)


def test_written_text_is_kept_and_missed_words_get_times_between_neighbours():
    spoken = heard("so today we relax every edge then we stop")
    lines = align(["So today, we relax every edge.", "Then we STOP!"], spoken)
    assert [text for _, _, text in lines] == ["So today, we relax every edge.", "Then we STOP!"]
    assert lines[0][:2] == (0, 2900) and lines[1][:2] == (3000, 4400)

    garbled = [(w if w != "relax" else "relapse", s, e) for w, s, e in spoken]
    assert align(["we relax every edge"], garbled)[0][:2] == (1000, 2900)


def test_chinese_is_matched_character_by_character():
    lines = align(
        ["今天讲最短路径。", "下课。"],
        [("今天讲", 0, 900), ("最短路径", 1000, 2000), ("下课", 3000, 3500)],
    )
    assert [line[:2] for line in lines] == [(0, 2000), (3000, 3500)]


def test_a_transcript_of_another_video_is_refused():
    with pytest.raises(PermanentError, match="0% of the transcript matches"):
        align(["completely different words here"], heard("nothing in common at all"))


def fake_whisper(monkeypatch, text):
    calls = []

    def whisper(audio_key, hotwords, language):
        calls.append(language)
        return [
            SimpleNamespace(
                words=[
                    SimpleNamespace(word=w, start=s / 1000, end=e / 1000) for w, s, e in heard(text)
                ]
            )
        ]

    monkeypatch.setattr(transcribe, "_whisper", whisper)
    return calls


def test_untimed_pdf_is_aligned_with_whisper_in_any_language(monkeypatch):
    monkeypatch.setattr(
        transcribe, "_read", lambda key: "Lecture notes\fWe relax edges. Then stop."
    )
    calls = fake_whisper(monkeypatch, "we relax edges then stop")
    lines = transcribe._from_upload("uploads/1/source.pdf", "audio", None)
    assert calls == [None]
    assert [text for _, _, text in lines] == ["Lecture notes We relax edges.", "Then stop."]


@pytest.mark.parametrize(
    ("key", "text", "message"),
    [
        ("uploads/1/source.srt", "words but no times", "no timestamps"),
        ("uploads/1/source.pdf", "\f\f", "scanned"),
    ],
)
def test_untimed_files_that_cannot_be_aligned_fail_with_a_reason(monkeypatch, key, text, message):
    monkeypatch.setattr(transcribe, "_read", lambda k: text)
    fake_whisper(monkeypatch, "anything")
    with pytest.raises(PermanentError, match=message):
        transcribe._from_upload(key, "audio", None)
