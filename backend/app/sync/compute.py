"""Builds the shot x slide score matrix from images on disk or in storage."""
from collections.abc import Sequence

import cv2
import numpy as np

from app.pipeline.ocr import read_text
from app.sync.scoring import TextScorer, combine, features, image_score

MATCH_WIDTH = 960


def _decode(data: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)


def _resized(gray: np.ndarray) -> np.ndarray:
    scale = MATCH_WIDTH / gray.shape[1]
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def score_matrix(
    shot_images: Sequence[bytes], slide_images: Sequence[bytes], slide_texts: list[str]
) -> np.ndarray:
    scorer = TextScorer(slide_texts)
    slide_features = [features(_resized(_decode(image))) for image in slide_images]
    matrix = np.zeros((len(shot_images), len(slide_images)))
    for row, image in enumerate(shot_images):
        text = scorer.scores(read_text(image))
        frame = features(_resized(_decode(image)))
        visual = np.array([image_score(frame, slide) for slide in slide_features])
        matrix[row] = combine(text, visual)
    return matrix
