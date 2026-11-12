"""The §14 test: our assistant against plain GLM-5.2 with no course data.

    cd backend && uv run python ../eval/run_eval.py ../eval/questions.json --out ../eval/report.json

Write 50 questions from a pilot course, in the shape of questions.example.json: 25
professor_specific, 15 general, 10 not_covered. Needs LLM_BASE_URL, and the login of a student
in EVAL_EMAIL and EVAL_PASSWORD.

GLM grades answers against your reference answers, so read report.json before trusting a number.
Citation support in particular should be spot-checked by a person.
"""
import argparse
import json
import os
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.core.llm import get_llm

JUDGE = """You grade a student assistant's answer against a reference answer written by the course
staff. It is correct if it states the same key facts. Extra detail is fine; contradiction is not."""
SUPPORT = """Does the quoted lecture passage support the claim? Answer true only if the passage
itself says what the claim says."""
MOMENT_TOLERANCE_MS = 15_000


class Verdict(BaseModel):
    correct: bool


def grade(llm, question: str, reference: str, answer: str) -> bool:
    prompt = f"Question: {question}\nReference: {reference}\nAnswer: {answer}"
    verdict = llm.complete_json(JUDGE, prompt, Verdict, max_tokens=64)
    return bool(verdict and verdict.correct)


def supported(llm, answer: dict) -> tuple[int, int]:
    good = 0
    for citation in answer["citations"]:
        prompt = f"Claim: {answer['text']}\nPassage: {citation['quote']}"
        verdict = llm.complete_json(SUPPORT, prompt, Verdict, max_tokens=64)
        good += bool(verdict and verdict.correct)
    return good, len(answer["citations"])


def share(values: list[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("questions", type=Path)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--out", type=Path, default=Path("report.json"))
    args = parser.parse_args()

    client = httpx.Client(base_url=args.url, trust_env=False, timeout=120)
    client.post(
        "/api/v1/auth/login",
        json={"email": os.environ["EVAL_EMAIL"], "password": os.environ["EVAL_PASSWORD"]},
    ).raise_for_status()
    llm = get_llm()

    rows = []
    for item in json.loads(args.questions.read_text()):
        chat = client.post(f"/api/v1/lessons/{item['lesson_id']}/chat/sessions").json()["id"]
        started = time.monotonic()
        response = client.post(
            f"/api/v1/chat/sessions/{chat}/messages",
            json={"text": item["question"], "current_time_ms": item["time_ms"]},
        )
        seconds = time.monotonic() - started
        response.raise_for_status()
        answer = response.json()
        baseline = llm.chat([{"role": "user", "content": item["question"]}], max_tokens=1024)

        row = {**item, "seconds": round(seconds, 2), "answer_given": answer, "baseline": baseline}
        if item["answer"]:
            row["correct"] = grade(llm, item["question"], item["answer"], answer["text"])
            row["baseline_correct"] = grade(llm, item["question"], item["answer"], baseline)
        if item["moment_ms"] is not None:
            row["near_moment"] = any(
                abs(c["start_ms"] - item["moment_ms"]) <= MOMENT_TOLERANCE_MS
                for c in answer["citations"]
            )
        row["supported"], row["cited"] = supported(llm, answer)
        rows.append(row)
        print(item["group"], answer["grounding"], f"{seconds:.1f}s", flush=True)

    specific = [r for r in rows if r["group"] == "professor_specific"]
    uncovered = [r for r in rows if r["group"] == "not_covered"]
    cited = sum(r["cited"] for r in rows)
    summary = {
        "correct_professor_specific (target 0.85)": share([r["correct"] for r in specific]),
        "baseline_professor_specific": share([r["baseline_correct"] for r in specific]),
        "citations_supported (target 0.95)": round(sum(r["supported"] for r in rows) / cited, 3)
        if cited
        else None,
        "citation_within_15s (target 0.90)": share(
            [r["near_moment"] for r in rows if "near_moment" in r]
        ),
        "uncovered_labelled (target 0.90)": share(
            [r["answer_given"]["grounding"] == "not_covered" for r in uncovered]
        ),
        "slowest_answer_seconds (target 15)": max((r["seconds"] for r in rows), default=None),
    }
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
