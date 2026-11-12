"""Drives a running system end to end through nginx, the way a browser does.

    cd backend && uv run python ../scripts/smoke_test.py SAMPLE_DIR [--url http://localhost:8080]

Needs ADMIN_EMAIL and ADMIN_PASSWORD from .env in the environment, and a student account named by
SMOKE_STUDENT_EMAIL and SMOKE_STUDENT_PASSWORD.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))
from sync_eval import accuracy  # noqa: E402

API = "/api/v1"
TIMEOUT_S = 3600
checks: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: object = "") -> None:
    checks.append((name, passed, str(detail)))
    print(f"{'ok  ' if passed else 'FAIL'} {name} {detail}", flush=True)


def session(url: str, email: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=url, trust_env=False, timeout=120)
    client.post(f"{API}/auth/login", json={"email": email, "password": password}).raise_for_status()
    return client


def upload(client: httpx.Client, lesson_id: int, path: Path, kind: str) -> dict:
    start = client.post(
        f"{API}/admin/lessons/{lesson_id}/uploads",
        json={"kind": kind, "filename": path.name, "size": path.stat().st_size},
    ).json()
    data = path.read_bytes()
    for part in start["parts"]:
        low = (part["part_number"] - 1) * start["part_size"]
        response = client.put(part["url"], content=data[low : low + start["part_size"]])
        response.raise_for_status()
    return start


def wait_for_review(client: httpx.Client, lesson_id: int) -> dict:
    deadline = time.monotonic() + TIMEOUT_S
    seen = ""
    while time.monotonic() < deadline:
        lesson = client.get(f"{API}/admin/lessons/{lesson_id}").json()
        revision = lesson["revisions"][0]
        line = " ".join(f"{s['name']}={s['status']}" for s in revision["stages"]
                        if s["status"] not in ("done", "skipped", "pending"))
        if line != seen:
            seen = line
            print("  ", revision["status"], line, flush=True)
        if revision["status"] == "needs_review":
            return revision
        if revision["status"] == "failed":
            errors = [s for s in revision["stages"] if s["status"] == "failed"]
            raise SystemExit(f"Pipeline failed: {errors}")
        time.sleep(5)
    raise SystemExit("Timed out waiting for the pipeline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", type=Path)
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()
    admin = session(args.url, os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    student = session(
        args.url, os.environ["SMOKE_STUDENT_EMAIL"], os.environ["SMOKE_STUDENT_PASSWORD"]
    )

    course = admin.post(f"{API}/admin/courses", json={"title": "Smoke test: Algorithms"}).json()
    lesson = admin.post(
        f"{API}/admin/lessons", json={"course_id": course["id"], "title": "Shortest paths"}
    ).json()

    video = upload(admin, lesson["id"], args.sample / "lecture.mp4", "video")
    deck = upload(admin, lesson["id"], args.sample / "lecture.pptx", "deck")
    first = admin.post(f"{API}/admin/uploads/{video['upload_id']}/complete").json()
    check("pipeline waits for the second upload", first["revision_id"] is None, first)
    second = admin.post(f"{API}/admin/uploads/{deck['upload_id']}/complete").json()
    check("last upload starts one revision", second["revision_id"] is not None, second)

    started = time.monotonic()
    revision = wait_for_review(admin, lesson["id"])
    print(f"   pipeline took {time.monotonic() - started:.0f}s", flush=True)
    for stage in revision["stages"]:
        if stage["started_at"] and stage["finished_at"]:
            print(f"   {stage['name']}: {stage['status']} attempts={stage['attempts']}")

    timeline = admin.get(f"{API}/admin/revisions/{revision['id']}/timeline").json()
    labels = json.loads((args.sample / "labels.json").read_text())
    score = accuracy(timeline["rows"], labels)
    check("slide sync at least 95% on a screen recording", score >= 0.95, f"{score:.1%}")
    check("hidden slide kept and marked",
          any(s["hidden"] and s["number"] == 3 for s in timeline["slides"]))
    check("timeline covers the whole video",
          timeline["rows"][0]["start_ms"] == 0
          and timeline["rows"][-1]["end_ms"] == timeline["duration_ms"])
    check("demo with no slide is off", any(r["slide"] is None for r in timeline["rows"]))

    url = f"{API}/lessons/{lesson['id']}/player"
    check("students cannot open an unpublished lesson", student.get(url).status_code == 404)
    draft = admin.get(f"{url}?revision_id={revision['id']}").json()
    check("draft blocks media for students",
          student.get(draft["hls_url"]).status_code in (401, 403))

    admin.post(f"{API}/admin/revisions/{revision['id']}/publish").raise_for_status()
    admin.patch(f"{API}/admin/courses/{course['id']}", json={"status": "published"})
    time.sleep(6)

    player = student.get(url).json()
    text = " ".join(s["text"] for s in player["transcript"]).lower()
    check("whisper heard the lecture", "relax" in text and "priority queue" in text)
    check("transcript has timestamps", player["transcript"][-1]["end_ms"] > 40_000)

    master = student.get(player["hls_url"])
    check("HLS master playlist streams", master.status_code == 200, master.status_code)
    variants = re.findall(r"^(?!#).+m3u8$", master.text, re.M)
    check("two renditions", len(variants) == 2, variants)
    base = player["hls_url"].rsplit("/", 1)[0]
    playlist = student.get(f"{base}/{variants[0]}").text
    segment = re.findall(r"^(?!#).+\.ts$", playlist, re.M)[0]
    folder = variants[0].rsplit("/", 1)[0]
    check("segment streams", student.get(f"{base}/{folder}/{segment}").status_code == 200)
    check("slide image loads", student.get(player["slides"][0]["image_url"]).status_code == 200)

    outsider = httpx.Client(base_url=args.url, trust_env=False)
    check("media needs a login", outsider.get(player["hls_url"]).status_code == 401)
    check("internal route is closed", outsider.get(f"{API}/internal/media-auth").status_code == 404)
    original = f"/media/uploads/{video['upload_id']}/source.mp4"
    check("original upload is not served", student.get(original).status_code in (401, 403))

    chat = student.post(f"{API}/lessons/{lesson['id']}/chat/sessions").json()["id"]
    answer = student.post(
        f"{API}/chat/sessions/{chat}/messages",
        json={"text": "What does relaxation do to the distance?", "current_time_ms": 40_000},
    )
    body = answer.json()
    print("   answer:", body)
    check("chat answers", answer.status_code == 200, answer.status_code)
    if answer.status_code == 200:
        check("citation points into the video", bool(body["citations"]), body["grounding"])
        check("invented tag was removed", "S999" not in body["text"])
    moved = admin.put(f"{API}/admin/revisions/{revision['id']}/timeline",
                      json={"rows": timeline["rows"]})
    check("timeline saves", moved.status_code == 204, moved.status_code)

    failed = [name for name, passed, _ in checks if not passed]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
