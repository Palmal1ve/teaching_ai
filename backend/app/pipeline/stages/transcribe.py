from datetime import UTC, datetime
from functools import lru_cache

from faster_whisper import WhisperModel
from sqlalchemy import delete, select

from app.core import storage
from app.core.config import get_settings
from app.core.db import session_scope
from app.models import Slide, TranscriptAsset, TranscriptSegment, VideoAsset
from app.pipeline.context import StageContext
from app.pipeline.errors import PermanentError
from app.pipeline.media import run as sh
from app.pipeline.media import work_dir
from app.pipeline.subtitles import decode, parse
from app.pipeline.transcript_align import align, sentences, tokens
from app.pipeline.vocabulary import deck_terms


@lru_cache
def _model() -> WhisperModel:
    return WhisperModel(get_settings().whisper_model, device="cpu", compute_type="int8")


def _read(key: str) -> str:
    if key.endswith(".pdf"):
        with work_dir() as out:
            return sh(["pdftotext", str(storage.download(key, out / "transcript.pdf")), "-"])
    return decode(storage.read_bytes(key))


def _whisper(audio_key: str, hotwords: str | None, language: str | None) -> list:
    with work_dir() as out:
        path = storage.download(audio_key, out / "audio.flac")
        segments, _ = _model().transcribe(
            str(path),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
            hotwords=hotwords,
        )
        return [s for s in segments if s.text.strip()]


def _from_upload(key: str, audio_key: str | None, hotwords: str | None) -> list[tuple]:
    """Timed files are used as they are. An untimed PDF is timed against what Whisper hears."""
    text = _read(key)
    lines = parse(text)
    if lines:
        return lines
    if not key.endswith(".pdf"):
        raise PermanentError(
            "The transcript has no timestamps. Check the file and upload it again."
        )
    if not tokens(text):
        raise PermanentError(
            "The PDF has no text in it, which usually means it is scanned. "
            "Upload a PDF exported from a text document."
        )
    heard = [
        (word.word, int(word.start * 1000), int(word.end * 1000))
        for segment in _whisper(audio_key, hotwords, language=None)
        for word in segment.words or []
    ]
    return align(sentences(text), heard)


def _segments(video_id: int, duration_ms: int, lines: list[tuple]) -> list[TranscriptSegment]:
    kept = [
        (start, min(end, duration_ms), text) for start, end, text in lines if start < duration_ms
    ]
    return [
        TranscriptSegment(video_asset_id=video_id, seq=seq, start_ms=start, end_ms=end, text=text)
        for seq, (start, end, text) in enumerate(kept)
    ]


def _save(video_id: int, rows: list[TranscriptSegment]) -> None:
    with session_scope() as session:
        session.execute(
            delete(TranscriptSegment).where(TranscriptSegment.video_asset_id == video_id)
        )
        session.add_all(rows)
        session.get(VideoAsset, video_id).transcribed_at = datetime.now(UTC)


def run(context: StageContext) -> None:
    with session_scope() as session:
        video = session.get(VideoAsset, context.video_id)
        transcript = (
            session.get(TranscriptAsset, video.transcript_asset_id)
            if video.transcript_asset_id
            else None
        )
        audio_key, duration_ms = video.audio_key, video.duration_ms
        hotwords = None
        if context.deck_id:
            slides = session.scalars(
                select(Slide).where(Slide.deck_asset_id == context.deck_id)
            ).all()
            hotwords = deck_terms([f"{s.text}\n{s.notes}" for s in slides]) or None

    if transcript is not None:
        lines = _from_upload(transcript.storage_key, audio_key, hotwords)
    else:
        lines = [
            (int(s.start * 1000), int(s.end * 1000), s.text.strip())
            for s in _whisper(audio_key, hotwords, language="en")
        ]
    _save(context.video_id, _segments(context.video_id, duration_ms, lines))
