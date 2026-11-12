"""Reads transcripts into (start_ms, end_ms, text) lines.

Two shapes are understood: .srt/.vtt cues ("00:00:01,000 --> 00:00:02,500"), and text where lines
start with a time ("00:01:23 text", "[1:23] text") or a speaker line ends with one ("Prof  1:23").
The second is what transcripts exported to PDF look like. A line without an end time runs until
the next one starts.
"""

import html
import re

from app.pipeline.errors import PermanentError

LAST_LINE_MS = 10_000

_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})"
_STAMP = r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE = re.compile(rf"{_TIME}\s*-->\s*{_TIME}")
_LEAD = re.compile(rf"^[\[(]?{_STAMP}[\])]?\s*[-–:]?\s*(.*)$")
_TAIL = re.compile(rf"^(.{{1,40}}?)\s+[\[(]?{_STAMP}[\])]?$")
_TAG = re.compile(r"<[^>]+>")


def _ms(hours: str | None, minutes: str, seconds: str, millis: str | None) -> int:
    whole = (int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)
    return whole * 1000 + int((millis or "0").ljust(3, "0"))


def _clean(rows: list[str]) -> str:
    return " ".join(html.unescape(_TAG.sub("", " ".join(rows))).split())


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PermanentError(
            "The transcript is not UTF-8 text. Save it as UTF-8 and upload again."
        ) from exc


def _cues(text: str) -> list[tuple[int, int, str]]:
    cues: list[tuple[int, int, list[str]]] = []
    for block in re.split(r"\n\s*\n", text):
        current = None
        for row in block.strip().split("\n"):
            match = _CUE.search(row)
            if match is None:
                if current is not None:
                    current[2].append(row.strip())
                continue
            if current is not None and current[2] and current[2][-1].isdigit():
                current[2].pop()
            groups = match.groups()
            current = (_ms(*groups[:4]), _ms(*groups[4:]), [])
            cues.append(current)
    return [(start, end, _clean(rows)) for start, end, rows in cues if _clean(rows)]


def _stamped(text: str) -> list[tuple[int, int, str]]:
    starts: list[tuple[int, list[str]]] = []
    for row in (r.strip() for r in text.split("\n")):
        if lead := _LEAD.match(row):
            starts.append((_ms(*lead.groups()[:4]), [lead[5]]))
        elif tail := _TAIL.match(row):
            starts.append((_ms(*tail.groups()[1:5]), []))
        elif starts and row:
            starts[-1][1].append(row)

    merged: list[tuple[int, str]] = []
    for start, rows in starts:
        words = _clean(rows)
        if not words:
            continue
        if merged and merged[-1][0] == start:
            merged[-1] = (start, f"{merged[-1][1]} {words}")
        else:
            merged.append((start, words))
    if not merged:
        return []
    ends = [start for start, _ in merged[1:]] + [merged[-1][0] + LAST_LINE_MS]
    return [(start, end, words) for (start, words), end in zip(merged, ends, strict=True)]


def parse(text: str) -> list[tuple[int, int, str]]:
    """Empty when the text carries no times at all."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    lines = _cues(text) or _stamped(text)
    for n in range(1, len(lines)):
        if lines[n][0] < lines[n - 1][0]:
            raise PermanentError(f"Transcript line {n + 1} starts before the line above it.")
    for n, (start, end, _) in enumerate(lines, 1):
        if end <= start:
            raise PermanentError(f"Transcript line {n} ends before it starts.")
    return lines
