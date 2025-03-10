FROM python:3.12.9-alpine3.21
COPY bot /app/bot
COPY requirement.txt /app/requirement.txt

ARG ROSETTA_VERSION
ENV ROSETTA_VERSION=$ROSETTA_VERSION

WORKDIR /app

RUN apk add ffmpeg
RUN pip install --no-cache-dir --upgrade -r requirement.txt

VOLUME [ "/app/music" ]
VOLUME [ "/app/mygo-ave-video" ]

WORKDIR /app/bot

CMD ["uvicorn", "bot:app"]