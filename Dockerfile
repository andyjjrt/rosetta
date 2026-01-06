FROM python:3.12.11-alpine3.21
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY rosetta /app/rosetta
COPY .python-version uv.lock pyproject.toml /app/

ARG ROSETTA_VERSION
ENV ROSETTA_VERSION=$ROSETTA_VERSION

WORKDIR /app

RUN apk update && apk add ffmpeg
RUN uv sync --frozen  --no-dev
# RUN uv add -U yt-dlp

VOLUME [ "/app/music" ]
VOLUME [ "/app/mygo-ave-video" ]

ENV LANGFUSE_TRACING_ENVIRONMENT=production

CMD ["/app/.venv/bin/python", "-m", "rosetta"]