# Rosetta

## Install
1. Create config fie `config.ini`
```ini
[bot]
TOKEN=xxx
CLIENT_ID=xxx
[bot.emoji]
success=<:name:xxx>
error=<:name:xxx>
youtube=<:name:xxx>
progress_start=<:name:xxx>
progress=<:name:xxx>
progress_mix=<:name:xxx>
progress_fill=<:name:xxx>
progress_end=<:name:xxx>
progress_fill_end=<:name:xxx>
progress_start_0=<:name:xxx>
```

2. Use [scripts/mygo-ave-preprocess.sh](scripts/mygo-ave-preprocess.sh) preprocess the video

3. Use `docker compose up -d` to start your service

```yml
services:
  rosetta:
    image: ghcr.io/andyjjrt/rosetta:latest
    volumes:
      - ./music:/app/music
      - ./config.ini:/app/config.ini
      - ./mygo-ave-video:/app/mygo-ave-video
```