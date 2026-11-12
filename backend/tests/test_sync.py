import cv2
import numpy as np

from app.sync.align import Interval, align, speech_timeline, visual_timeline
from app.sync.scoring import TextScorer, combine, features, image_score
from app.sync.shots import collapse
from app.sync.viterbi import best_path


def one_hot(path, slides, strength=0.9, noise=0.05):
    matrix = np.full((len(path), slides), noise)
    for row, state in enumerate(path):
        if state is not None:
            matrix[row, state] = strength
    return matrix


def test_follows_the_deck_in_order():
    assert best_path(one_hot([0, 0, 1, 2, 3], 4)) == [0, 0, 1, 2, 3]


def test_professor_can_jump_backwards():
    assert best_path(one_hot([0, 1, 2, 3, 1, 1, 1], 4)) == [0, 1, 2, 3, 1, 1, 1]


def test_single_noisy_shot_is_ignored():
    scores = one_hot([1, 1, 1, 1, 1], 6)
    scores[2] = 0.05
    scores[2, 5] = 0.4
    assert best_path(scores) == [1, 1, 1, 1, 1]


def test_duplicate_slides_resolve_by_position_in_the_deck():
    # Slides 1 and 4 are the same agenda slide: the path decides, not the single shot.
    scores = one_hot([0, 1, 2, 3, None, 5], 6)
    scores[4, 1] = scores[4, 4] = 0.9
    assert best_path(scores)[4] == 4


def test_demo_with_no_matching_slide_is_off():
    slides = 3
    assert best_path(one_hot([0, None, None, None, 1], slides))[1:4] == [slides] * 3


def test_half_revealed_slide_still_matches_by_containment():
    scorer = TextScorer(
        [
            "Edge relaxation updates distance estimates using shorter paths found",
            "Greedy choice property proves correctness of Dijkstra",
        ]
    )
    scores = scorer.scores("Edge relaxation updates distance")
    assert scores[0] == 1.0
    assert scores[1] == 0.0


def test_template_words_count_for_little():
    template = "Algorithms 101 University"
    scorer = TextScorer([f"{template} heaps priority", f"{template} graphs traversal",
                         f"{template} sorting merge"])
    assert scorer.scores(f"{template} graphs traversal").argmax() == 1


def test_frame_chrome_does_not_lower_the_score():
    scorer = TextScorer(["heaps priority queue operations"])
    assert scorer.scores("heaps priority queue Zoom Meeting Recording Participants")[0] == 1.0


def test_too_few_words_gives_no_text_evidence():
    assert TextScorer(["heaps priority queue"]).scores("heaps").max() == 0.0


def test_combine_keeps_a_single_strong_signal():
    assert combine(np.array([0.9]), np.array([0.0]))[0] > 0.7


def test_shots_collapse_and_cover_the_video():
    a = np.zeros(256, dtype=bool)
    b = a.copy()
    b[:100] = True
    shots = collapse([a, a, a, b, b], 10_000)
    assert shots == [{"start_ms": 0, "end_ms": 6000}, {"start_ms": 6000, "end_ms": 10_000}]


def test_a_rounded_up_last_frame_cannot_make_an_empty_shot():
    a = np.zeros(256, dtype=bool)
    b = a.copy()
    b[:100] = True
    shots = collapse([a, a, b], 3900)
    assert shots == [{"start_ms": 0, "end_ms": 3900}]


def test_visual_timeline_covers_video_and_marks_off():
    shots = [{"start_ms": i * 1000, "end_ms": (i + 1) * 1000} for i in range(4)]
    rows = visual_timeline(shots, one_hot([0, 0, None, None], 2))
    assert [(r.start_ms, r.end_ms, r.slide) for r in rows] == [(0, 2000, 0), (2000, 4000, None)]


def spoken_embed(texts):
    vocabulary = ["heap", "graph"]
    return [[float(word in t.lower()) + 1e-6 for word in vocabulary] for t in texts]


def test_speech_fallback_when_slides_are_never_visible():
    segments = [
        {"start_ms": 0, "end_ms": 60_000, "text": "the heap property"},
        {"start_ms": 60_000, "end_ms": 120_000, "text": "the graph traversal"},
    ]
    shots = [{"start_ms": 0, "end_ms": 120_000}]
    rows = align(shots, np.zeros((1, 2)), segments, ["heap", "graph"], 120_000, spoken_embed)
    assert [(r.slide, r.method) for r in rows] == [(0, "speech"), (1, "speech")]
    assert rows[0].start_ms == 0 and rows[-1].end_ms == 120_000


def test_speech_timeline_with_silence_stays_off():
    vectors = np.eye(2)
    rows = speech_timeline([], 0, 60_000, vectors, spoken_embed)
    assert rows == [Interval(0, 60_000, None, 0.0, "speech")]


def rendered_slide(title, bullets):
    image = np.full((540, 960), 255, dtype=np.uint8)
    cv2.rectangle(image, (0, 0), (960, 80), 40, -1)
    cv2.putText(image, title, (30, 55), cv2.FONT_HERSHEY_DUPLEX, 1.3, 255, 2)
    for index, bullet in enumerate(bullets):
        cv2.putText(image, bullet, (50, 150 + index * 70), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 20, 2)
    return image


FIRST = rendered_slide("Dijkstra", ["Greedy choice of closest", "Priority queue of distances"])
SECOND = rendered_slide("Bellman Ford", ["Handles negative edges", "Detects negative cycles"])


def test_same_template_and_font_is_not_an_image_match():
    assert image_score(features(FIRST), features(SECOND)) < 0.3


def test_the_true_slide_is_an_image_match():
    assert image_score(features(FIRST), features(FIRST.copy())) == 1.0


def test_a_camera_angle_still_matches():
    corners = np.float32([[0, 0], [960, 0], [960, 540], [0, 540]])
    skewed = np.float32([[60, 30], [900, 0], [940, 530], [20, 500]])
    warp = cv2.getPerspectiveTransform(corners, skewed)
    filmed = cv2.warpPerspective(FIRST, warp, (960, 540), borderValue=120)
    filmed = cv2.GaussianBlur(filmed, (3, 3), 0)
    assert image_score(features(filmed), features(FIRST)) > 0.5
    assert image_score(features(filmed), features(SECOND)) < 0.3


def test_a_clear_slide_right_after_a_demo_is_not_swallowed_by_off():
    slides = 5
    path = best_path(one_hot([0, 1, 3, None, 4, 1], slides, strength=1.0, noise=0.01))
    assert path == [0, 1, 3, slides, 4, 1]
