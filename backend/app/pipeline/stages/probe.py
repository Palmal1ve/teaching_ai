from app.core import storage
from app.core.config import get_settings
from app.core.db import session_scope
from app.models import VideoAsset
from app.pipeline.context import StageContext
from app.pipeline.errors import PermanentError
from app.pipeline.media import ffprobe


def run(context: StageContext) -> None:
    with session_scope() as session:
        key = session.get(VideoAsset, context.video_id).storage_key
    try:
        info = ffprobe(storage.internal_url(key))
    except RuntimeError as exc:
        raise PermanentError(f"This file is not a readable video: {exc}") from exc

    streams = info.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    if video is None:
        raise PermanentError("This file has no video stream.")
    if not any(s["codec_type"] == "audio" for s in streams):
        raise PermanentError("This video has no audio, so it cannot be transcribed.")
    duration_ms = int(float(info["format"]["duration"]) * 1000)
    if duration_ms > get_settings().max_video_ms:
        raise PermanentError("This video is longer than the 3 hour limit.")

    with session_scope() as session:
        asset = session.get(VideoAsset, context.video_id)
        asset.duration_ms = duration_ms
        asset.width = video["width"]
        asset.height = video["height"]
