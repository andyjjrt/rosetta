FROM python:3.12.9-alpine3.21
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ADD . /app

ARG ROSETTA_VERSION
ENV ROSETTA_VERSION=$ROSETTA_VERSION

WORKDIR /app

RUN apk add ffmpeg
RUN uv sync --frozen  --no-dev
# RUN uv add -U yt-dlp

VOLUME [ "/app/music" ]
VOLUME [ "/app/mygo-ave-video" ]

CMD ["sh", "-c", "uv add -U yt-dlp && uv run uvicorn main:app"]