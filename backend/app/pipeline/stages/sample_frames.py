import json

import cv2

from app.core import storage
from app.core.db import session_scope
from app.models import VideoAsset
from app.pipeline.context import StageContext
from app.pipeline.media import run as sh
from app.pipeline.media import work_dir
from app.sync.shots import FRAME_INTERVAL_MS, collapse, frame_hash

KEYFRAME_WIDTH = 1280


def run(context: StageContext) -> None:
    with session_scope() as session:
        video = session.get(VideoAsset, context.video_id)
        source, duration_ms = video.storage_key, video.duration_ms
    url = storage.internal_url(source)
    prefix = f"videos/{context.video_id}/shots"

    with work_dir() as out:
        frames = out / "frames"
        frames.mkdir()
        sh(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", url,
                "-vf", f"fps=1000/{FRAME_INTERVAL_MS},scale=320:-2",
                "-q:v", "5", str(frames / "%06d.jpg"),
            ]
        )
        paths = sorted(frames.glob("*.jpg"))
        hashes = [frame_hash(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)) for p in paths]
        shots = collapse(hashes, duration_ms)

        keyframes = out / "keyframes"
        keyframes.mkdir()
        for index, shot in enumerate(shots):
            shot["key"] = f"{prefix}/{index:05d}.jpg"
            middle = (shot["start_ms"] + shot["end_ms"]) / 2000
            sh(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{middle:.3f}", "-i", url,
                    "-frames:v", "1", "-vf", f"scale='min({KEYFRAME_WIDTH},iw)':-2",
                    "-q:v", "3", str(keyframes / f"{index:05d}.jpg"),
                ]
            )
        storage.upload_dir(keyframes, prefix)

    shots_key = f"{prefix}/shots.json"
    storage.put_bytes(shots_key, json.dumps(shots).encode(), "application/json")
    with session_scope() as session:
        session.get(VideoAsset, context.video_id).shots_key = shots_key
