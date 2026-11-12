import re
from collections import Counter

STOPWORDS = frozenset(
    """about above after again all also and any are because been before being below between both
    but can could did does doing down during each few for from further had has have having here
    how into its just like more most much must not now off once only other our out over own same
    she should some such than that the their them then there these they this those through too
    under until very was were what when where which while who why will with would you
    your""".split()
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]{3,}")
MAX_TERMS = 60


def deck_terms(texts: list[str]) -> str:
    """Terms worth biasing Whisper towards. Capitalised words beat plain words, then frequency."""
    counts: Counter[str] = Counter()
    for text in texts:
        for word in _WORD.findall(text):
            if word.lower() not in STOPWORDS:
                counts[word] += 3 if word[0].isupper() else 1
    merged: dict[str, tuple[int, str]] = {}
    for word, count in counts.items():
        total, best = merged.get(word.lower(), (0, word))
        merged[word.lower()] = (total + count, best if best[0].isupper() else word)
    ranked = sorted(merged.values(), key=lambda item: -item[0])
    return " ".join(word for _, word in ranked[:MAX_TERMS])
