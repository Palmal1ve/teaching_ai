"""Gives an untimed transcript the times at which Whisper heard the same words.

The admin's text is kept word for word. Whisper only supplies timing: both texts become token
lists (words, or single characters for Chinese and Japanese), difflib pairs up the tokens they
share, and tokens Whisper missed get times interpolated between their matched neighbours.
"""

import re
from difflib import SequenceMatcher

import numpy as np

from app.pipeline.errors import PermanentError

MAX_TOKENS = 40
MIN_MATCHED = 0.2

_CJK = r"぀-ヿ㐀-鿿豈-﫿"
_TOKEN = re.compile(rf"[{_CJK}]|[^\W{_CJK}]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])")
_CLAUSE_END = re.compile(r"(?<=[,;:，；：、])\s*")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _pack(pieces: list[str]) -> list[str]:
    lines, current = [], ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if current and len(tokens(candidate)) > MAX_TOKENS:
            lines.append(current)
            candidate = piece
        current = candidate
    return lines + [current] if current else lines


def sentences(text: str) -> list[str]:
    """Transcript lines: sentences, with long ones broken at commas."""
    lines = []
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        if len(tokens(sentence)) > MAX_TOKENS:
            lines.extend(_pack(_CLAUSE_END.split(sentence)))
        elif sentence.strip():
            lines.append(sentence.strip())
    return [line for line in lines if tokens(line)]


def align(lines: list[str], words: list[tuple[str, int, int]]) -> list[tuple[int, int, str]]:
    heard = [(token, start, end) for word, start, end in words for token in tokens(word)]
    written, spans = [], []
    for line in lines:
        first = len(written)
        written.extend(tokens(line))
        spans.append((first, len(written) - 1))

    matcher = SequenceMatcher(None, written, [token for token, _, _ in heard], autojunk=False)
    anchors = [
        (a + k, heard[b + k][1], heard[b + k][2])
        for a, b, size in matcher.get_matching_blocks()
        for k in range(size)
    ]
    if not written or len(anchors) < MIN_MATCHED * len(written):
        share = round(100 * len(anchors) / max(len(written), 1))
        raise PermanentError(
            f"Only {share}% of the transcript matches what is said in the video. "
            "Check that it is the transcript of this video."
        )

    index, starts, ends = (np.array(column) for column in zip(*anchors, strict=True))
    positions = np.arange(len(written))
    token_start = np.interp(positions, index, starts)
    token_end = np.interp(positions, index, ends)

    result = []
    for line, (first, last) in zip(lines, spans, strict=True):
        start, end = int(token_start[first]), int(token_end[last])
        result.append((start, max(end, start + 1), line))
    return result
