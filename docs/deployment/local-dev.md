# Local Development

Run Rosetta from source for development and testing.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **[FFmpeg](https://ffmpeg.org/)** — required for MyGO GIF generation
- **Docker** — for running Lavalink locally

## Start Lavalink

The dev compose file starts two Lavalink 4.2.2 nodes on ports 2333 and 2334:

Its JVM uses IPv4 for media requests, and the Docker bridge MTU is pinned to 1280 to avoid unrouted IPv6 and PMTU black holes common under WSL, Hyper-V, and VPN networking.

```bash
docker compose -f docker-compose.dev.yaml up -d
```

??? example "docker-compose.dev.yaml — Lavalink default"
    ```yaml
    services:
      lavalink:
        image: ghcr.io/lavalink-devs/lavalink:4.2.2-alpine
        restart: unless-stopped
        environment:
          _JAVA_OPTIONS: "-Xmx6G -Djava.net.preferIPv4Stack=true"
        volumes:
          - ./application.yml:/opt/Lavalink/application.yml
        ports:
          - "2333:2333"

      lavalink-1:
        image: ghcr.io/lavalink-devs/lavalink:4.2.2-alpine
        restart: unless-stopped
        environment:
          _JAVA_OPTIONS: "-Xmx6G -Djava.net.preferIPv4Stack=true"
        volumes:
          - ./application.yml:/opt/Lavalink/application.yml
        ports:
          - "2334:2333"

    networks:
      default:
        driver: bridge
        driver_opts:
          com.docker.network.driver.mtu: "1280"
    ```

### NodeLink Alternative

If you prefer NodeLink, start two NodeLink 3.6.0 nodes instead:

```bash
docker compose -f docker-compose.nodelink.yaml up -d
```

??? example "docker-compose.nodelink.yaml — NodeLink alternative"
    ```yaml
    services:
      nodelink:
        image: performanc/nodelink:3.6.0
        restart: unless-stopped
        ports:
          - "2333:3000"
        environment:
          NODELINK_SERVER_HOST: "0.0.0.0"
          NODELINK_SERVER_PORT: "3000"
          NODELINK_SERVER_PASSWORD: "youshallnotpass"

      nodelink-1:
        image: performanc/nodelink:3.6.0
        restart: unless-stopped
        ports:
          - "2334:3000"
        environment:
          NODELINK_SERVER_HOST: "0.0.0.0"
          NODELINK_SERVER_PORT: "3000"
          NODELINK_SERVER_PASSWORD: "youshallnotpass"
    ```

### Stop Lavalink / NodeLink

```bash
# Stop Lavalink
docker compose -f docker-compose.dev.yaml down

# Or stop NodeLink
docker compose -f docker-compose.nodelink.yaml down
```

## Install Dependencies

```bash
uv sync
```

## Environment Variables

Copy the example file and set the required values. Rosetta loads `.env` from the current working directory, and exported variables take precedence:

```bash
cp .env.example .env
# Edit .env with your bot token, client ID, and optional integrations.
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
    ├── config.py        # Pydantic settings (env vars)
    ├── embeds.py        # Discord embed templates
    ├── log.py           # Structured logging setup
    ├── player.py        # Custom lava_lyra player with queue
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
