from app.knowledge.extraction import (
    ExtractedRelation,
    ExtractedStatement,
    Extraction,
    TermFix,
    Unit,
    apply_fix,
    verify,
)

UNIT = Unit(
    index=0,
    segments={4: "So we relax the edges here,", 5: "and you will trace this by hand."},
    slide_text="Dijkstra's algorithm: edge relaxation",
)


def extraction(statements=(), relations=(), term_fixes=()):
    return Extraction(
        concepts=[],
        statements=list(statements),
        relations=list(relations),
        term_fixes=list(term_fixes),
    )


def statement(quote, ids=(4,), kind="explanation"):
    return ExtractedStatement(kind=kind, text="x", segment_ids=list(ids), quote=quote)


def test_glm_cannot_leave_out_a_section_of_the_reply():
    required = Extraction.model_json_schema()["required"]
    assert set(required) == {"concepts", "statements", "relations", "term_fixes"}


def test_keeps_statement_whose_quote_is_in_the_cited_segment():
    result, rejected = verify(extraction([statement("relax the edges")]), UNIT)
    assert rejected == 0 and len(result["statements"]) == 1


def test_quote_match_ignores_case_and_punctuation():
    result, _ = verify(extraction([statement("RELAX the edges here")]), UNIT)
    assert len(result["statements"]) == 1


def test_quote_can_span_two_cited_segments():
    reply = extraction([statement("edges here and you will", ids=(4, 5))])
    assert verify(reply, UNIT)[1] == 0


def test_rejects_invented_quote():
    assert verify(extraction([statement("the professor never said this")]), UNIT)[1] == 1


def test_rejects_unknown_segment_id():
    assert verify(extraction([statement("relax the edges", ids=(99,))]), UNIT)[1] == 1


def test_rejects_quote_from_a_segment_it_did_not_cite():
    assert verify(extraction([statement("trace this by hand", ids=(4,))]), UNIT)[1] == 1


def test_relation_on_a_rejected_statement_is_dropped_and_others_renumbered():
    reply = extraction(
        statements=[statement("invented"), statement("relax the edges")],
        relations=[
            ExtractedRelation(source="a", target="b", type="USED_FOR", statement_index=0),
            ExtractedRelation(source="a", target="c", type="IS_A", statement_index=1),
        ],
    )
    result, _ = verify(reply, UNIT)
    assert [(r["target"], r["statement_index"]) for r in result["relations"]] == [("c", 0)]


def test_term_fix_needs_the_right_spelling_on_the_slide():
    unit = Unit(0, {1: "the dike stra method"}, "Dijkstra")
    reply = extraction(
        term_fixes=[
            TermFix(heard="dike stra", correct="Dijkstra"),
            TermFix(heard="method", correct="Algorithm X"),
        ]
    )
    assert verify(reply, unit)[0]["term_fixes"] == [{"heard": "dike stra",
                                                          "correct": "Dijkstra"}]


def test_apply_fix_replaces_whole_words_only():
    assert apply_fix("Dike stra and dike straw", "dike stra", "Dijkstra") == (
        "Dijkstra and dike straw"
    )
