from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings

MEDIA_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".json": "application/json",
}


@lru_cache
def client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            max_pool_connections=16,
        ),
    )


def bucket() -> str:
    return get_settings().s3_bucket


def ensure_bucket() -> None:
    try:
        client().head_bucket(Bucket=bucket())
    except ClientError:
        client().create_bucket(Bucket=bucket())


def internal_url(key: str, expires: int = 24 * 3600) -> str:
    """Presigned GET that ffmpeg can read directly, so large sources are never copied locally."""
    return client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires
    )


def browser_url(internal: str) -> str:
    """nginx restores the signed Host and path, so one URL works on localhost and on the LAN."""
    endpoint = get_settings().s3_endpoint.rstrip("/")
    return get_settings().s3_public_prefix + internal.removeprefix(endpoint)


def sign_part(key: str, upload_id: str, part_number: int) -> str:
    url = client().generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": bucket(),
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=24 * 3600,
    )
    return browser_url(url)


def download(key: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    client().download_file(bucket(), key, str(path))
    return path


def upload_file(path: Path, key: str) -> None:
    content_type = MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    client().upload_file(str(path), bucket(), key, ExtraArgs={"ContentType": content_type})


def upload_dir(directory: Path, prefix: str) -> None:
    files = [p for p in directory.rglob("*") if p.is_file()]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda p: upload_file(p, f"{prefix}/{p.relative_to(directory)}"), files))


def read_bytes(key: str) -> bytes:
    return client().get_object(Bucket=bucket(), Key=key)["Body"].read()


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


def delete_prefix(prefix: str) -> None:
    paginator = client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if objects:
            client().delete_objects(Bucket=bucket(), Delete={"Objects": objects})
