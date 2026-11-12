from app.core import storage
from app.core.db import session_scope
from app.models import VideoAsset
from app.pipeline.context import StageContext
from app.pipeline.media import run as sh
from app.pipeline.media import work_dir

SEGMENT_S = 6


def run(context: StageContext) -> None:
    with session_scope() as session:
        source = session.get(VideoAsset, context.video_id).storage_key
    prefix = f"videos/{context.video_id}/hls"
    with work_dir() as out:
        sh(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", storage.internal_url(source),
                "-filter_complex",
                "[0:v]split=2[a][b];"
                "[a]scale=-2:'min(720,ih)'[v720];[b]scale=-2:'min(360,ih)'[v360]",
                "-map", "[v720]", "-map", "[v360]", "-map", "0:a:0", "-map", "0:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "main",
                "-pix_fmt", "yuv420p", "-sc_threshold", "0",
                "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_S})",
                "-b:v:0", "1400k", "-maxrate:v:0", "1800k", "-bufsize:v:0", "2800k",
                "-b:v:1", "500k", "-maxrate:v:1", "650k", "-bufsize:v:1", "1000k",
                "-c:a", "aac", "-b:a", "96k", "-ac", "2",
                "-f", "hls", "-hls_time", str(SEGMENT_S), "-hls_playlist_type", "vod",
                "-hls_segment_filename", str(out / "v%v/seg_%05d.ts"),
                "-master_pl_name", "master.m3u8",
                "-var_stream_map", "v:0,a:0 v:1,a:1",
                str(out / "v%v/index.m3u8"),
            ]
        )
        storage.upload_dir(out, prefix)
    with session_scope() as session:
        session.get(VideoAsset, context.video_id).hls_key = f"{prefix}/master.m3u8"
