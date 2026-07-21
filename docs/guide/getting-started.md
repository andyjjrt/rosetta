# Getting Started

Rosetta is a Discord bot built with [discord.py](https://github.com/Rapptz/discord.py). It provides music playback, LLM-powered chat, image generation, and MyGO!!!!! anime GIF generation.

## Tech Stack

- **Python 3.12** with [discord.py](https://github.com/Rapptz/discord.py)
- **Lavalink** via [lava-lyra](https://github.com/ParrotXray/lava-lyra) for music playback
- **OpenAI-compatible API** for LLM chat & image generation
- **Langfuse** for LLM observability & tracing
- **FFmpeg** + **ffmpeg-python** for GIF generation
- **Kubernetes** client for Lavalink node auto-discovery
- **uv** for dependency management
- **Docker** (Alpine-based) for deployment

## Quick Start

The fastest way to get Rosetta running is with Docker Compose:

```bash
docker compose up -d
```

See [Docker Compose Deployment](/deployment/docker-compose) for the full setup, or [Local Development](/deployment/local-dev) to run from source.

## Prerequisites

Before deploying, you'll need:

1. A **Discord bot token** — create one at the [Discord Developer Portal](https://discord.com/developers/applications)
2. A **Lavalink server** — included in the Docker Compose setup
3. _(Optional)_ An **OpenAI-compatible API** endpoint for LLM features
4. _(Optional)_ A **Langfuse** instance for LLM observability

## Discord Application Emojis

Upload the following emojis to your Discord application for the bot UI to work correctly:

- `success`, `error`, `youtube`
- `progress_start`, `progress`, `progress_mix`, `progress_fill`
- `progress_end`, `progress_fill_end`, `progress_start_0`

## MyGO Video Data

If you want to use the `/mygo` command, preprocess the anime video data:

```bash
bash scripts/mygo-ave-preprocess.sh
```

This generates the video segments and metadata in the `mygo-ave-video/` directory.
