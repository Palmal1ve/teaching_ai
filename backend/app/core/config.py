from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://course:course@postgres:5432/course"
    redis_url: str = "redis://redis:6379/0"

    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "course-media"
    s3_public_prefix: str = "/s3"
    upload_part_size: int = 64 * 1024 * 1024
    max_video_bytes: int = 10 * 1024**3
    max_deck_bytes: int = 500 * 1024**2
    max_transcript_bytes: int = 20 * 1024**2
    max_video_ms: int = 3 * 60 * 60 * 1000

    jwt_secret: str
    jwt_ttl_hours: int = 24 * 14
    demo_login: bool = False

    embedder_url: str = "http://embedder:8000"
    whisper_model: str = ""
    convert_dir: str = "/convert"
    work_dir: str = "/work"

    questions_per_day: int = 50
    citation_min_similarity: float = 0.5
    context_token_budget: int = 8000
    answer_max_tokens: int = 2048
    extraction_max_tokens: int = 4096


@lru_cache
def get_settings() -> Settings:
    return Settings()
