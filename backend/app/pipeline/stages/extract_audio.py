from app.core import storage
from app.core.db import session_scope
from app.models import VideoAsset
from app.pipeline.context import StageContext
from app.pipeline.media import run as sh
from app.pipeline.media import work_dir


def run(context: StageContext) -> None:
    with session_scope() as session:
        source = session.get(VideoAsset, context.video_id).storage_key
    key = f"videos/{context.video_id}/audio.flac"
    with work_dir() as out:
        path = out / "audio.flac"
        sh(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", storage.internal_url(source),
                "-vn", "-ac", "1", "-ar", "16000", str(path),
            ]
        )
        storage.upload_file(path, key)
    with session_scope() as session:
        session.get(VideoAsset, context.video_id).audio_key = key
