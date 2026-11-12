from app.assistant.answer import without_marks
from app.assistant.citations import check, sentences, split_sections, word_count
from app.assistant.retrieval import Source
from app.models import ChatMessage
from tests.conftest import fake_vector


def embed(texts):
    return [fake_vector(t) for t in texts]


def source(text, start_ms=754_000, slide=7):
    return Source(("passage", 1), 42, 4, start_ms, start_ms + 30_000, slide, text, text[:50])


RELAX = source("we relax the edges because a shorter path might appear later")
GREEDY = source("the greedy choice only works with non negative edge weights", 2_462_000, 19)
MIN = 0.3


def test_valid_tag_becomes_a_numbered_citation_with_a_timestamp():
    result = check("We relax the edges because a shorter path might appear [S1].",
                   [RELAX], embed, MIN)
    assert result.text == "We relax the edges because a shorter path might appear. [1]"
    assert result.citations[0]["start_ms"] == 754_000
    assert result.citations[0]["slide"] == 7
    assert result.citations[0]["label"] == "12:34"
    assert result.grounding == "grounded"


def test_tag_after_the_full_stop_is_understood():
    result = check("We relax the edges because a shorter path appears. [S1]", [RELAX], embed, MIN)
    assert len(result.citations) == 1


def test_unknown_tag_is_removed():
    result = check("Shorter paths might appear when we relax [S9].", [RELAX], embed, MIN)
    assert "[S9]" not in result.text and "[" not in result.text
    assert result.citations == []
    assert result.grounding == "not_covered"


def test_citation_on_an_unrelated_sentence_is_dropped():
    result = check("Bananas grow in tropical climates around the world [S1].", [RELAX], embed, MIN)
    assert result.citations == []


def test_only_the_supported_source_survives_on_one_sentence():
    text = "We relax the edges because a shorter path might appear [S1][S2]."
    result = check(text, [RELAX, GREEDY], embed, MIN)
    assert [c["start_ms"] for c in result.citations] == [754_000]


def test_numbers_follow_first_appearance_and_repeat_for_the_same_source():
    text = (
        "The greedy choice only works with non negative edge weights [S2]. "
        "We relax the edges because a shorter path might appear [S1]. "
        "Again the greedy choice works with non negative edge weights [S2]."
    )
    result = check(text, [RELAX, GREEDY], embed, MIN)
    assert [c["start_ms"] for c in result.citations] == [2_462_000, 754_000]
    assert result.text.count("[1]") == 2 and result.text.count("[2]") == 1


def test_beyond_section_is_kept_marks_partial_and_loses_tags():
    text = (
        "We relax the edges because a shorter path might appear [S1].\n\n"
        "## Beyond the class material\nBellman-Ford also handles negative edges [S1]."
    )
    result = check(text, [RELAX], embed, MIN)
    assert result.grounding == "partial"
    assert "Bellman-Ford also handles negative edges." in result.text
    assert len(result.citations) == 1


def test_answer_only_from_outside_the_class_is_not_covered():
    text = "The class did not cover this.\n\nBeyond the class material\nHere is an answer."
    result = check(text, [RELAX], embed, MIN)
    assert result.grounding == "not_covered" and result.citations == []


def test_many_uncited_sentences_means_partial():
    text = (
        "We relax the edges because a shorter path might appear [S1]. "
        "This next sentence has plenty of words but carries no citation at all. "
        "Neither does this other sentence which also makes a long claim."
    )
    assert check(text, [RELAX], embed, MIN).grounding == "partial"


def test_decimal_numbers_do_not_end_a_sentence():
    assert len(sentences("The ratio is 3.14 here [S1]. Next one.")) == 2


def test_split_finds_a_bold_heading():
    assert split_sections("a\n**Beyond the class material**\nb")[1].startswith("**Beyond")


def test_two_tags_at_the_same_place_give_one_citation():
    twin = source(RELAX.text)
    text = "We relax the edges because a shorter path might appear [S1][S2]."
    result = check(text, [RELAX, twin], embed, MIN)
    assert len(result.citations) == 1
    assert result.text == "We relax the edges because a shorter path might appear. [1]"


def test_same_place_keeps_one_number_across_sentences():
    twin = source(RELAX.text)
    text = (
        "We relax the edges because a shorter path might appear [S1]. "
        "Again we relax the edges because a shorter path might appear [S2]."
    )
    result = check(text, [RELAX, twin], embed, MIN)
    assert len(result.citations) == 1
    assert result.text.count("[1]") == 2


def test_tags_shown_as_the_same_clock_time_give_one_citation():
    twin = source(RELAX.text, start_ms=754_600)
    text = "We relax the edges because a shorter path might appear [S1][S2]."
    assert len(check(text, [RELAX, twin], embed, MIN).citations) == 1


def test_same_time_on_another_slide_or_lesson_stays_separate():
    other_slide = source(RELAX.text, slide=8)
    other_lesson = source(RELAX.text)
    other_lesson.lesson_id = 43
    text = "We relax the edges because a shorter path might appear [S1][S2][S3]."
    assert len(check(text, [RELAX, other_slide, other_lesson], embed, MIN).citations) == 3


def test_unsupported_tag_at_a_place_does_not_block_the_supported_one():
    unrelated = source("bananas grow in tropical climates around the world")
    text = "We relax the edges because a shorter path might appear [S1][S2]."
    result = check(text, [unrelated, RELAX], embed, MIN)
    assert result.citations[0]["quote"] == RELAX.quote


def test_mark_stays_inside_a_table_row():
    text = "| Dijkstra | We relax the edges because a shorter path might appear [S1] |\n"
    result = check(text, [RELAX], embed, MIN)
    assert result.text.endswith("might appear [1] |\n")


def test_history_keeps_array_indexing_and_drops_real_marks():
    answer = ChatMessage(
        role="assistant", content="Set dist[1] and list [7] to zero. [1]", citations=[{"n": 1}]
    )
    assert without_marks(answer) == "Set dist[1] and list [7] to zero."


def test_history_leaves_student_messages_alone():
    question = ChatMessage(role="user", content="What is dist [1] here?")
    assert without_marks(question) == "What is dist [1] here?"


def test_chinese_sentences_split_on_chinese_punctuation():
    assert len(sentences("第一句话[S1]。第二句话。[S2]第三句话！第四句话？")) == 4


def test_chinese_tags_stay_with_their_sentence():
    parts = sentences("第一句话。[S1]第二句话。")
    assert parts[0] == "第一句话。[S1]" and parts[1] == "第二句话。"


def test_uncited_chinese_sentences_mean_partial():
    text = (
        "We relax the edges because a shorter path might appear [S1]."
        "这句话没有任何引用但是它提出了一个很长的主张内容。"
        "这一句同样没有引用而且也提出了很长的主张内容。"
    )
    assert check(text, [RELAX], embed, MIN).grounding == "partial"


def test_short_chinese_remark_is_not_counted():
    text = "We relax the edges because a shorter path might appear [S1].好的。"
    assert check(text, [RELAX], embed, MIN).grounding == "grounded"


def test_word_count_handles_mixed_text():
    assert word_count("Dijkstra 算法只适用于非负权边") == 6
    assert word_count("three plain words") == 3
