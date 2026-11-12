from functools import lru_cache

import numpy as np
from rapidocr_onnxruntime import RapidOCR


@lru_cache
def _engine() -> RapidOCR:
    return RapidOCR()


def read_text(image: np.ndarray | bytes) -> str:
    result, _ = _engine()(image)
    return "\n".join(line[1] for line in result) if result else ""
