# Rosetta

## Install
1. Create config file `config.ini` or use environment variables
```ini
[bot]
TOKEN=xxx
CLIENT_ID=xxx

[llm]
BASE_URL=xxx
API_KEY=xxx
DEFAULT_MODEL=xxx

[langfuse]
PUBLIC_KEY=xxx
SECRET_KEY=xxx
HOST=xxx
```

Environment variables can also be used:
- `BOT_TOKEN`, `BOT_CLIENT_ID`
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_DEFAULT_MODEL`
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

2. Upload emojis to your Discord application with these names:
   - `success`, `error`, `youtube`
   - `progress_start`, `progress`, `progress_mix`, `progress_fill`
   - `progress_end`, `progress_fill_end`, `progress_start_0`

3. Use [scripts/mygo-ave-preprocess.sh](scripts/mygo-ave-preprocess.sh) preprocess the video

4. Use `docker compose up -d` to start your service

```yml
services:
  rosetta:
    image: ghcr.io/andyjjrt/rosetta:latest
    volumes:
      - ./music:/app/music
      - ./config.ini:/app/config.ini
      - ./mygo-ave-video:/app/mygo-ave-video
```