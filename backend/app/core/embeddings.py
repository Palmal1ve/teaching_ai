from functools import lru_cache

import httpx
import numpy as np

from app.core.config import get_settings

DIMENSIONS = 1024
_BATCH = 32


class EmbedderUnavailable(Exception):
    pass


@lru_cache
def _client() -> httpx.Client:
    return httpx.Client(base_url=get_settings().embedder_url, timeout=300, trust_env=False)


def embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), _BATCH):
            response = _client().post("/embed", json={"texts": texts[start : start + _BATCH]})
            response.raise_for_status()
            vectors.extend(response.json()["vectors"])
    except httpx.HTTPError as exc:
        raise EmbedderUnavailable(type(exc).__name__) from exc
    return vectors


def cosine(a: list[float], b: list[float]) -> float:
    x, y = np.asarray(a), np.asarray(b)
    return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))
