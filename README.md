# Rosetta

## Install
1. Create config fie `config.ini`
```ini
[bot]
TOKEN=xxx
CLIENT_ID=xxx
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