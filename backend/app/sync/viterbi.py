"""Picks the best slide path across all shots, rather than the best slide for each shot alone."""
import numpy as np

OFF_SCORE = 0.22
FLOOR = 1e-3
NEXT_COST = 0.1
SKIP_COST = 1.0
BACK_COST = 1.5
JUMP_COST = 3.0
OFF_COST = 2.0
MAX_SKIP = 3
EVIDENCE_SCALE = 2.5


def transition_matrix(slides: int) -> np.ndarray:
    """Log-probabilities over `slides` states plus a final OFF state."""
    size = slides + 1
    matrix = np.full((size, size), -JUMP_COST)
    for source in range(slides):
        matrix[source, source] = 0.0
        if source + 1 < slides:
            matrix[source, source + 1] = -NEXT_COST
        for step in range(2, MAX_SKIP + 1):
            if source + step < slides:
                matrix[source, source + step] = -SKIP_COST
        if source > 0:
            matrix[source, source - 1] = -BACK_COST
    matrix[:, slides] = -OFF_COST
    matrix[slides, :] = -OFF_COST
    matrix[slides, slides] = 0.0
    return matrix


def best_path(scores: np.ndarray, weights: np.ndarray | None = None) -> list[int]:
    """`scores` is shots x slides in [0, 1]. Returns one state per shot; `slides` means OFF."""
    shots, slides = scores.shape
    weights = EVIDENCE_SCALE * (np.ones(shots) if weights is None else weights)
    emissions = np.log(
        np.maximum(np.hstack([scores, np.full((shots, 1), OFF_SCORE)]), FLOOR)
    ) * weights[:, None]
    transitions = transition_matrix(slides)

    best = emissions[0].copy()
    best[:slides] += -0.1 * np.arange(slides) / max(slides, 1)
    back = np.zeros((shots, slides + 1), dtype=int)
    for t in range(1, shots):
        candidates = best[:, None] + transitions
        back[t] = candidates.argmax(axis=0)
        best = candidates.max(axis=0) + emissions[t]

    path = [int(best.argmax())]
    for t in range(shots - 1, 0, -1):
        path.append(int(back[t, path[-1]]))
    return path[::-1]
