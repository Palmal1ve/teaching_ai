"""GLM's tags are not trusted. Each one is checked here before a student sees the answer."""
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.assistant.prompt import BEYOND_HEADING, clock
from app.assistant.retrieval import Source
from app.core.embeddings import cosine

_TAG = re.compile(r"\s*\[S(\d+)\]")
_TAG_RUN = r"(?:\s*\[S\d+\](?:\s*,\s*(?=\[S))?)*"
_END = r"(?:[.!?]+(?=\s|\[|$)|[。！？]+)"
_SENTENCE = re.compile(rf"[^\n]+?(?:{_TAG_RUN}{_END}{_TAG_RUN}|$)|\n+", re.M)
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_BEYOND = re.compile(rf"^[ \t]*(?:#+[ \t]*|\*\*)?{re.escape(BEYOND_HEADING)}", re.I | re.M)
MIN_WORDS_TO_COUNT = 6
CJK_CHARS_PER_WORD = 2
MAX_UNCITED_SHARE = 0.34


@dataclass
class CheckedAnswer:
    text: str
    citations: list[dict]
    grounding: str


def split_sections(answer: str) -> tuple[str, str]:
    match = _BEYOND.search(answer)
    return (answer[: match.start()], answer[match.start():]) if match else (answer, "")


def sentences(text: str) -> list[str]:
    return [m.group(0) for m in _SENTENCE.finditer(text)]


def _plain(sentence: str) -> str:
    return _TAG.sub("", sentence).strip()


def word_count(text: str) -> int:
    return len(_CJK.sub(" ", text).split()) + len(_CJK.findall(text)) // CJK_CHARS_PER_WORD


def _place(source: Source) -> tuple:
    return source.lesson_id, clock(source.start_ms), source.slide


def _citation(number: int, source: Source) -> dict:
    return {
        "n": number,
        "lesson_id": source.lesson_id,
        "start_ms": source.start_ms,
        "label": clock(source.start_ms),
        "slide": source.slide,
        "quote": source.quote,
    }


def _with_marks(body: str, marks: str) -> str:
    stripped = body.rstrip()
    if not stripped:
        return body
    tail = body[len(stripped):]
    if stripped.endswith("|"):
        return f"{stripped[:-1].rstrip()}{marks} |{tail}"
    return f"{stripped}{marks}{tail}"


def check(
    answer: str,
    sources: list[Source],
    embed: Callable[[list[str]], list[list[float]]],
    min_similarity: float,
) -> CheckedAnswer:
    class_part, beyond_part = split_sections(answer)
    beyond_part = _TAG.sub("", beyond_part)
    parts = sentences(class_part)

    pairs: list[tuple[int, int]] = []
    for index, part in enumerate(parts):
        for tag in dict.fromkeys(int(t) for t in _TAG.findall(part)):
            if 1 <= tag <= len(sources):
                pairs.append((index, tag))

    cited = sorted({tag for _, tag in pairs})
    claims = sorted({index for index, _ in pairs})
    vectors = embed([_plain(parts[i]) for i in claims] + [sources[t - 1].text for t in cited])
    claim_vector = dict(zip(claims, vectors[: len(claims)], strict=True))
    source_vector = dict(zip(cited, vectors[len(claims):], strict=True))
    supported = {
        (index, tag)
        for index, tag in pairs
        if cosine(claim_vector[index], source_vector[tag]) >= min_similarity
    }

    numbers: dict[tuple, int] = {}
    citations: list[dict] = []
    rendered: list[str] = []
    uncited = counted = 0
    for index, part in enumerate(parts):
        kept = [sources[tag - 1] for i, tag in pairs if i == index and (i, tag) in supported]
        places: dict[tuple, Source] = {}
        for source in kept:
            places.setdefault(_place(source), source)
        for place, source in places.items():
            if place not in numbers:
                numbers[place] = len(numbers) + 1
                citations.append(_citation(numbers[place], source))
        marks = "".join(f" [{numbers[place]}]" for place in places)
        rendered.append(_with_marks(_TAG.sub("", part), marks))
        if word_count(_plain(part)) >= MIN_WORDS_TO_COUNT:
            counted += 1
            uncited += not kept

    if not citations:
        grounding = "not_covered"
    elif beyond_part.strip() or (counted and uncited / counted > MAX_UNCITED_SHARE):
        grounding = "partial"
    else:
        grounding = "grounded"
    return CheckedAnswer("".join(rendered) + beyond_part, citations, grounding)
