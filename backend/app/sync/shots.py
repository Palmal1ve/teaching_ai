"""Collapses frames sampled every 2 seconds into stable shots, using perceptual hashes."""
import cv2
import numpy as np

FRAME_INTERVAL_MS = 2000
HASH_SIZE = 16
CHANGE_THRESHOLD = 10


def frame_hash(gray: np.ndarray) -> np.ndarray:
    small = cv2.resize(gray, (HASH_SIZE + 1, HASH_SIZE), interpolation=cv2.INTER_AREA)
    return (small[:, 1:] > small[:, :-1]).ravel()


def collapse(hashes: list[np.ndarray], duration_ms: int) -> list[dict]:
    if not hashes:
        return [{"start_ms": 0, "end_ms": duration_ms}]
    shots = []
    start, anchor = 0, hashes[0]
    for index, current in enumerate(hashes[1:], start=1):
        if int(np.count_nonzero(anchor != current)) > CHANGE_THRESHOLD:
            shots.append({"start_ms": start * FRAME_INTERVAL_MS,
                          "end_ms": index * FRAME_INTERVAL_MS})
            start, anchor = index, current
    shots.append({"start_ms": start * FRAME_INTERVAL_MS, "end_ms": duration_ms})
    if len(shots) > 1 and shots[-1]["start_ms"] >= duration_ms:
        shots.pop()
        shots[-1]["end_ms"] = duration_ms
    return shots
