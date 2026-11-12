"""Shared helpers for media stages. ffmpeg reads sources straight from storage by URL."""
import json
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings


def run(cmd: list[str], timeout: int | None = None) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {done.stderr[-1500:]}")
    return done.stdout


def ffprobe(url: str) -> dict:
    return json.loads(
        run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", url,
            ]
        )
    )


@contextmanager
def work_dir() -> Iterator[Path]:
    root = Path(get_settings().work_dir)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)
