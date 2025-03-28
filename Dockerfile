FROM python:3.12.9-alpine3.21
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ADD . /app

ARG ROSETTA_VERSION
ENV ROSETTA_VERSION=$ROSETTA_VERSION

WORKDIR /app

RUN apk add ffmpeg
RUN uv sync --frozen  --no-dev

VOLUME [ "/app/music" ]
VOLUME [ "/app/mygo-ave-video" ]

CMD ["uv", "run", "uvicorn", "main:app"]