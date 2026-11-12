"""Scores one shot against every slide with two signals: OCR text and image features."""
import math
import re
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

_WORD = re.compile(r"[a-z0-9]{3,}")
MIN_FRAME_WORDS = 3
ORB_FEATURES = 600
RATIO = 0.75
MIN_MATCHES = 8
NOISE_INLIER_SHARE = 0.1
FULL_INLIER_SHARE = 0.35


def words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class TextScorer:
    """Containment of frame words in a slide, weighted so template words count for little.

    Only words found somewhere in the deck count, so a webcam label or browser chrome in the
    frame cannot lower the score. A half-revealed animated slide still scores 1.0.
    """

    def __init__(self, slide_texts: list[str]) -> None:
        self.slides = [words(text) for text in slide_texts]
        counts = Counter(word for slide in self.slides for word in slide)
        total = max(len(self.slides), 1)
        self.idf = {word: math.log(1 + total / count) for word, count in counts.items()}

    def scores(self, frame_text: str) -> np.ndarray:
        frame = {word for word in words(frame_text) if word in self.idf}
        result = np.zeros(len(self.slides))
        if len(frame) < MIN_FRAME_WORDS:
            return result
        total = sum(self.idf[word] for word in frame)
        for index, slide in enumerate(self.slides):
            result[index] = sum(self.idf[word] for word in frame & slide) / total
        return result


@dataclass
class ImageFeatures:
    keypoints: tuple
    descriptors: np.ndarray | None


def features(gray: np.ndarray) -> ImageFeatures:
    keypoints, descriptors = cv2.ORB_create(ORB_FEATURES).detectAndCompute(gray, None)
    return ImageFeatures(keypoints, descriptors)


def image_score(frame: ImageFeatures, slide: ImageFeatures) -> float:
    """ORB matches checked by a homography, which tolerates cropping and a camera's angle.

    Scored as a share of all features: slides sharing a template and font still give dozens of
    chance inliers, while the true slide matches most of its features.
    """
    if frame.descriptors is None or slide.descriptors is None:
        return 0.0
    if len(frame.descriptors) < 2 or len(slide.descriptors) < 2:
        return 0.0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(frame.descriptors, slide.descriptors, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < RATIO * p[1].distance]
    if len(good) < MIN_MATCHES:
        return 0.0
    source = np.float32([frame.keypoints[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    target = np.float32([slide.keypoints[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
    if mask is None:
        return 0.0
    share = int(mask.sum()) / min(len(frame.keypoints), len(slide.keypoints))
    span = FULL_INLIER_SHARE - NOISE_INLIER_SHARE
    return float(np.clip((share - NOISE_INLIER_SHARE) / span, 0.0, 1.0))


def combine(text: np.ndarray, image: np.ndarray) -> np.ndarray:
    """Either signal alone can identify a slide; agreement between them raises the score."""
    return np.clip(np.maximum(text, image) * 0.8 + np.minimum(text, image) * 0.2, 0.0, 1.0)
