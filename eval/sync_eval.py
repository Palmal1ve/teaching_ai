"""Measures slide sync against hand labels: the share of video time on the correct slide.

    python eval/sync_eval.py labels.json REVISION_ID --url http://localhost:8080

labels.json is a list of {"start_ms", "end_ms", "slide"}. Slide numbers start at 1, and null means
no slide is on screen. Needs ADMIN_EMAIL and ADMIN_PASSWORD in the environment.
"""
import argparse
import json
import os
from pathlib import Path


def accuracy(rows: list[dict], labels: list[dict]) -> float:
    total = correct = 0
    for label in labels:
        total += label["end_ms"] - label["start_ms"]
        for row in rows:
            overlap = min(row["end_ms"], label["end_ms"]) - max(row["start_ms"], label["start_ms"])
            if overlap > 0 and row["slide"] == label["slide"]:
                correct += overlap
    return correct / total if total else 0.0


def main() -> None:
    import httpx

    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("revision", type=int)
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.url, trust_env=False, timeout=60)
    client.post(
        "/api/v1/auth/login",
        json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]},
    ).raise_for_status()
    timeline = client.get(f"/api/v1/admin/revisions/{args.revision}/timeline").json()
    print(f"{accuracy(timeline['rows'], json.loads(args.labels.read_text())):.1%} of video time "
          "shows the correct slide")


if __name__ == "__main__":
    main()
