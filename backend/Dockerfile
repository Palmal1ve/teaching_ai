FROM python:3.12-slim AS base
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=$UV_DEFAULT_INDEX UV_LINK_MODE=copy UV_HTTP_TIMEOUT=120 \
    PATH=/srv/.venv/bin:$PATH PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir --index-url $UV_DEFAULT_INDEX uv
WORKDIR /srv
RUN useradd --create-home --uid 1000 app

FROM base AS api
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER app

FROM base AS media
ARG APT_MIRROR=deb.debian.org
RUN sed -i "s/deb.debian.org/$APT_MIRROR/g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg poppler-utils libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra media --no-install-project
COPY app ./app
RUN mkdir -p /work /models /convert && chown app /work /models /convert
USER app
