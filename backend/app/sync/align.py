"""Turns shots, slides and transcript into a timeline. No database, so Phase 0 can call it too."""
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from app.sync.viterbi import best_path

LOW_CONFIDENCE = 0.35
NEVER_VISIBLE_COVERAGE = 0.2
WINDOW_MS = 60_000
SIMILARITY_FLOOR = 0.3
SIMILARITY_RANGE = 0.4


@dataclass
class Interval:
    start_ms: int
    end_ms: int
    slide: int | None
    confidence: float
    method: str


def _merge(rows: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for row in rows:
        last = merged[-1] if merged else None
        if last and last.slide == row.slide and last.method == row.method:
            first_span = last.end_ms - last.start_ms
            second_span = row.end_ms - row.start_ms
            span = max(first_span + second_span, 1)
            last.confidence = (
                last.confidence * first_span + row.confidence * second_span
            ) / span
            last.end_ms = row.end_ms
        else:
            merged.append(row)
    return merged


def visual_timeline(shots: list[dict], scores: np.ndarray) -> list[Interval]:
    durations = np.array([s["end_ms"] - s["start_ms"] for s in shots], dtype=float)
    weights = np.clip(1 + durations / 30_000, 1, 3)
    path = best_path(scores, weights)
    slides = scores.shape[1]
    rows = []
    for shot, state, row in zip(shots, path, scores, strict=True):
        off = state == slides
        confidence = 1 - float(row.max()) if off else float(row[state])
        rows.append(
            Interval(shot["start_ms"], shot["end_ms"], None if off else state, confidence, "visual")
        )
    return _merge(rows)


def _windows(segments: list[dict], start_ms: int, end_ms: int) -> list[tuple[int, int, str]]:
    windows = []
    cursor = start_ms
    while cursor < end_ms:
        stop = min(cursor + WINDOW_MS, end_ms)
        text = " ".join(
            s["text"] for s in segments if s["end_ms"] > cursor and s["start_ms"] < stop
        )
        windows.append((cursor, stop, text))
        cursor = stop
    return windows


def speech_timeline(
    segments: list[dict],
    start_ms: int,
    end_ms: int,
    slide_vectors: np.ndarray,
    embed: Callable[[list[str]], list[list[float]]],
) -> list[Interval]:
    windows = _windows(segments, start_ms, end_ms)
    spoken = [(i, w) for i, w in enumerate(windows) if w[2].strip()]
    if not spoken:
        return [Interval(start_ms, end_ms, None, 0.0, "speech")]
    vectors = np.asarray(embed([w[2] for _, w in spoken]))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9
    scores = np.zeros((len(windows), slide_vectors.shape[0]))
    for row, (index, _) in zip(vectors @ slide_vectors.T, spoken, strict=True):
        scores[index] = np.clip((row - SIMILARITY_FLOOR) / SIMILARITY_RANGE, 0, 1)
    path = best_path(scores)
    slides = slide_vectors.shape[0]
    rows = []
    for (start, stop, _), state, row in zip(windows, path, scores, strict=True):
        off = state == slides
        rows.append(
            Interval(start, stop, None if off else state,
                     0.0 if off else float(row[state]), "speech")
        )
    return _merge(rows)


def align(
    shots: list[dict],
    scores: np.ndarray,
    segments: list[dict],
    slide_texts: list[str],
    duration_ms: int,
    embed: Callable[[list[str]], list[list[float]]],
) -> list[Interval]:
    """Visual timeline first, then speech wherever the picture cannot say which slide is up."""
    timeline = visual_timeline(shots, scores)
    vectors = np.asarray(embed(slide_texts))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9

    on_slide = sum(i.end_ms - i.start_ms for i in timeline if i.slide is not None)
    if on_slide < NEVER_VISIBLE_COVERAGE * duration_ms:
        return speech_timeline(segments, 0, duration_ms, vectors, embed)

    result: list[Interval] = []
    for interval in timeline:
        if interval.slide is not None and interval.confidence < LOW_CONFIDENCE:
            result.extend(
                speech_timeline(segments, interval.start_ms, interval.end_ms, vectors, embed)
            )
        else:
            result.append(interval)
    return _merge(result)
