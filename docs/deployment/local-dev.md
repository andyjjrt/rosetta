# Local Development

Run Rosetta from source for development and testing.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **[FFmpeg](https://ffmpeg.org/)** — required for MyGO GIF generation
- **Docker** — for running Lavalink locally

## Start Lavalink

The dev compose file starts two Lavalink nodes on ports 2333 and 2334:

```bash
docker compose -f docker-compose.dev.yaml up -d
```

??? example "docker-compose.dev.yaml"
    ```yaml
    services:
      lavalink:
        image: ghcr.io/lavalink-devs/lavalink:4-alpine
        container_name: lavalink
        restart: unless-stopped
        environment:
          - _JAVA_OPTIONS=-Xmx6G
        volumes:
          - ./application.yml:/opt/Lavalink/application.yml
        ports:
          - "2333:2333"

      lavalink-1:
        image: ghcr.io/lavalink-devs/lavalink:4-alpine
        container_name: lavalink-1
        restart: unless-stopped
        environment:
          - _JAVA_OPTIONS=-Xmx6G
        volumes:
          - ./application.yml:/opt/Lavalink/application.yml
        ports:
          - "2334:2333"
    ```

## Install Dependencies

```bash
uv sync
```

## Environment Variables

Set the required environment variables. You can export them or create a `.env` file:

```bash
export BOT_TOKEN=your-bot-token
export BOT_CLIENT_ID=your-client-id
export BOT_DEBUG=true
export LAVALINK_HOST=127.0.0.1
export LAVALINK_PORT=2333
export LAVALINK_PASSWORD=youshallnotpass

# LLM (optional)
export LLM_BASE_URL=https://api.example.com/v1
export LLM_API_KEY=your-api-key
export LLM_DEFAULT_MODEL=gpt-4

# Langfuse (optional)
export LANGFUSE_PUBLIC_KEY=pk-...
export LANGFUSE_SECRET_KEY=sk-...
export LANGFUSE_HOST=https://langfuse.example.com
```

## Run the Bot

```bash
uv run python -m rosetta
```

## Project Structure

```
rosetta/
├── __main__.py          # Bot entry point
├── commands/
│   ├── basics.py        # /ping, /version, !guilds
│   ├── llm.py           # /llm chat, /llm list, /llm image
│   ├── music.py         # /play, /search, /skip, /shuffle, etc.
│   └── mygo.py          # /mygo GIF generation
└── utils/
    ├── cog.py           # Base cog class with logging
    ├── config.py         # Pydantic settings (env vars)
    ├── embeds.py        # Discord embed templates
    ├── log.py           # Structured logging setup
    ├── player.py        # Custom Pomice player with queue
    └── views/           # Interactive Discord UI views
        ├── Guilds.py
        ├── Image.py
        ├── LLM.py
        ├── NowPlaying.py
        └── Search.py
```

## Code Quality

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .
```

[pre-commit](https://pre-commit.com/) is available for git hooks:

```bash
uv run pre-commit install
```
