# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.9.27 AS uv

FROM python:3.13-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/ai-video-worker

COPY pyproject.toml uv.lock README.md ./
COPY ai_video_editor ./ai_video_editor
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        ffmpeg \
        libgomp1 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 ai-video-worker \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin ai-video-worker \
    && mkdir -p \
        /var/lib/ai-video-worker/state \
        /var/lib/ai-video-worker/scratch \
        /var/log/ai-video-worker \
    && chown -R ai-video-worker:ai-video-worker \
        /var/lib/ai-video-worker \
        /var/log/ai-video-worker

COPY --from=builder /opt/ai-video-worker /opt/ai-video-worker

ENV PATH="/opt/ai-video-worker/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIDEO_PROCESSING_STATE_DB_PATH=/var/lib/ai-video-worker/state/jobs.sqlite3 \
    VIDEO_PROCESSING_SCRATCH_DIR=/var/lib/ai-video-worker/scratch \
    VIDEO_PROCESSING_LOG_DIR=/var/log/ai-video-worker

USER 10001:10001
EXPOSE 8000

ENTRYPOINT ["ai-video-worker"]
