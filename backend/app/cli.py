"""python -m app.cli init | fetch-models | create-user EMAIL PASSWORD [--role admin|student]"""
import argparse
import json
import os
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core import storage
from app.core.db import session_scope
from app.core.security import hash_password
from app.models import User

PUBLIC_MEDIA = ["videos/*/hls/*", "videos/*/shots/*", "decks/*/slides/*"]

MODELS = {
    "/models/embedder/bge-m3": (
        "BAAI/bge-m3",
        ["modules.json", "config_sentence_transformers.json", "sentence_bert_config.json",
         "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
         "sentencepiece.bpe.model", "1_Pooling/config.json", "pytorch_model.bin"],
    ),
}


def download(client: httpx.Client, url: str, target: Path) -> None:
    """Resumes a partial file, so a dropped connection does not restart a 2 GB download."""
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    done = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code == 416:
            partial.rename(target)
            return
        response.raise_for_status()
        mode = "ab" if response.status_code == 206 else "wb"
        with partial.open(mode) as file:
            for chunk in response.iter_bytes(1024 * 1024):
                file.write(chunk)
    partial.rename(target)
    print(f"Downloaded {target}", flush=True)


def fetch_models() -> None:
    host = os.environ.get("MODEL_HOST", "https://huggingface.co").rstrip("/")
    revision = os.environ.get("MODEL_REVISION", "main")
    timeout = httpx.Timeout(60, read=120)
    with httpx.Client(follow_redirects=True, timeout=timeout, trust_env=False) as client:
        for directory, (repo, files) in MODELS.items():
            for name in files:
                url = f"{host}/{repo}/resolve/{revision}/{name}"
                download(client, url, Path(directory) / name)


def create_user(email: str, password: str, role: str) -> None:
    with session_scope() as session:
        user = session.scalars(select(User).where(User.email == email.lower())).first()
        if user is None:
            session.add(
                User(email=email.lower(), password_hash=hash_password(password), role=role)
            )
            print(f"Created {role} {email}")
        else:
            print(f"{email} already exists")


def init() -> None:
    """MinIO is never published. Only nginx reaches it, after auth_request has said yes."""
    storage.ensure_bucket()
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{storage.bucket()}/{path}" for path in PUBLIC_MEDIA],
            }
        ],
    }
    storage.client().put_bucket_policy(Bucket=storage.bucket(), Policy=json.dumps(policy))
    email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if email and password:
        create_user(email, password, "admin")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("fetch-models")
    user = commands.add_parser("create-user")
    user.add_argument("email")
    user.add_argument("password")
    user.add_argument("--role", choices=["admin", "student"], default="student")
    args = parser.parse_args()
    if args.command == "init":
        init()
    elif args.command == "fetch-models":
        fetch_models()
    else:
        create_user(args.email, args.password, args.role)


if __name__ == "__main__":
    main()
