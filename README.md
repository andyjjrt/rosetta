# Rosetta

A Discord bot with music playback, LLM chat, image generation, and MyGO anime GIF features. Built with [discord.py](https://github.com/Rapptz/discord.py) and [Lavalink](https://github.com/lavalink-devs/Lavalink).

## Features

### 🎵 Music

Powered by [Lavalink](https://github.com/lavalink-devs/Lavalink) via [lava-lyra](https://github.com/ParrotXray/lava-lyra). Supports Kubernetes-based Lavalink node discovery for multi-node setups.

| Command | Description |
|---------|-------------|
| `/play <url>` | Play a YouTube URL (supports playlists). Options: `loop`, `shuffle`, `top`, `node_name` |
| `/search <keyword>` | Search YouTube and select a track interactively |
| `/nowplaying` | Show the currently playing track with a progress bar |
| `/skip` | Skip to the next song in the queue |
| `/shuffle` | Shuffle the current queue |
| `/loop <Off\|One\|Queue>` | Set the loop mode |
| `/leave` | Disconnect the bot from the voice channel |
| `/switchnode <node>` | Switch to a different Lavalink node |

### 🤖 LLM

Chat and image generation via an OpenAI-compatible API, with [Langfuse](https://langfuse.com/) observability.

| Command | Description |
|---------|-------------|
| `/llm chat <prompt>` | Chat with an LLM. Supports text and image attachments (vision) |
| `/llm list` | List available models |
| `/llm image <prompt>` | Generate an image from a text prompt (admin only) |

### 🎬 MyGO

Generate GIFs from MyGO!!!!! anime scenes.

| Command | Description |
|---------|-------------|
| `/mygo <text>` | Search for a scene by subtitle text, then generate and send a GIF. Options: `resolution` (240p/360p/720p), `ephemeral` |

### 🛠️ Utilities

| Command | Description |
|---------|-------------|
| `/ping` | Check bot / Lavalink node latency |
| `/version` | Show bot version, Python/discord.py versions (admins see extended stats) |
| `!guilds` | List all guilds the bot is in (owner only, prefix command) |
| `!reload_nodes` | Reload Lavalink nodes (owner only, prefix command) |

---

## Configuration

Configuration is done via **environment variables**:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Discord bot token |
| `BOT_CLIENT_ID` | Discord application client ID |
| `BOT_DEBUG` | Enable debug logging (`true`/`false`) |
| `LLM_BASE_URL` | OpenAI-compatible API base URL |
| `LLM_API_KEY` | API key for the LLM provider |
| `LLM_DEFAULT_MODEL` | Default model for `/llm chat` |
| `LLM_IMAGE_API_KEY` | API key for image generation (can differ from chat key) |
| `LLM_IMAGE_MODEL` | Model for `/llm image` (default: `dall-e-3`) |
| `LAVALINK_DISCOVERY_MODE` | `local` (default) or `k8s` for Kubernetes node discovery |
| `LAVALINK_HOST` | Lavalink host (default: `127.0.0.1`) |
| `LAVALINK_PORT` | Lavalink port (default: `2333`) |
| `LAVALINK_PASSWORD` | Lavalink password (default: `youshallnotpass`) |
| `LAVALINK_LOCAL_NODE_COUNT` | Number of sequential local nodes (default: `2`, production: `1`, ignored in `k8s` mode) |
| `LAVALINK_K8S_NAMESPACE` | Kubernetes namespace for Lavalink service discovery |
| `LAVALINK_K8S_SERVICE_NAME` | Kubernetes service name for Lavalink |
| `LAVALINK_K8S_SERVICE_PORT` | Kubernetes service port for Lavalink |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host URL |
| `MCP_ENABLED` | Enable the private MCP Streamable HTTP endpoint (`false` by default) |
| `MCP_HOST` | Bind host for the MCP listener (default: `127.0.0.1`) |
| `MCP_PORT` | Bind port for the MCP listener (default: `8000`) |
| `MCP_PATH` | MCP mount path, starting with one `/` (default: `/mcp`) |
| `MCP_BEARER_TOKEN` | Required bearer secret when MCP is enabled; at least 32 characters |
| `MCP_ALLOWED_HOSTS` | JSON list of accepted HTTP Host values, e.g. `["127.0.0.1", "localhost"]` |

### Private MCP search/play endpoint

MCP is disabled by default and is intended only for a private operator network or sidecar path. It is not an internet-facing API boundary. When `MCP_ENABLED=true`, set a high-entropy `MCP_BEARER_TOKEN`; clients must send `Authorization: Bearer <token>`, and Rosetta rejects missing or wrong credentials with HTTP 401 before MCP dispatch. Shutdown is managed with the bot lifecycle, so closing Rosetta requests graceful Streamable HTTP listener cleanup.

The endpoint is stable MCP v1 Streamable HTTP, stateless JSON, mounted at `http://<MCP_HOST>:<MCP_PORT><MCP_PATH>/`. It exposes exactly two tools:

```json
{
  "search": {
    "keyword": "string, trimmed, min length 1",
    "limit": "integer, default 10, range 1..25"
  },
  "play": {
    "user_id": "decimal string Discord user ID",
    "voice_channel_id": "decimal string Discord voice channel ID",
    "url": "string, trimmed, min length 1",
    "loop": "Off | One | Queue, default Off",
    "shuffle": "boolean, default false",
    "top": "boolean, default false",
    "node_name": "string or null, default null"
  }
}
```

`search` returns `{status:"success", ok:true, tracks:[{title, author, duration_ms, uri, thumbnail}]}`. Feed a returned `tracks[0].uri` to `play`; Discord IDs must stay JSON strings, not numbers. Expected music failures are structured tool results with `{status:"failure", ok:false, code, message}`. Common operator-relevant codes are `player_channel_conflict` when the guild player is already in another voice channel, `user_not_in_channel` when the requested user/channel do not match cached Discord voice state, and `music_backend_unavailable` when no Lavalink node is ready. Malformed tool input remains an MCP validation error.

```python
# mcp-client-snippet:start
from __future__ import annotations

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run_mcp_search_play(
    mcp_url: str,
    bearer_token: str,
    keyword: str,
    user_id: str,
    voice_channel_id: str,
) -> dict[str, object]:
    import httpx2

    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=httpx2.Timeout(30.0, read=300.0),
        follow_redirects=True,
    ) as http_client:
        async with streamable_http_client(
            mcp_url,
            http_client=http_client,
        ) as (read_stream, write_stream, _session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                search = await session.call_tool("search", {"keyword": keyword})
                uri = search.structuredContent["result"]["tracks"][0]["uri"]
                play = await session.call_tool(
                    "play",
                    {
                        "user_id": user_id,
                        "voice_channel_id": voice_channel_id,
                        "url": uri,
                    },
                )
                return {
                    "tools": [tool.name for tool in tools.tools],
                    "search": search.structuredContent,
                    "play": play.structuredContent,
                }
# mcp-client-snippet:end
```

### Discord Application Emojis

Upload the following emojis to your Discord application:

- `success`, `error`, `youtube`
- `progress_start`, `progress`, `progress_mix`, `progress_fill`
- `progress_end`, `progress_fill_end`, `progress_start_0`

### MyGO Video Data

Use the preprocessing script to prepare the anime video data:

```bash
bash scripts/mygo-ave-preprocess.sh
```

---

## Deployment

### Docker Compose (Production)

The simplest way to run Rosetta with Lavalink:

```yaml
# docker-compose.yml
services:
  rosetta:
    image: ghcr.io/andyjjrt/rosetta:latest
    restart: unless-stopped
    depends_on:
      lavalink:
        condition: service_started
    environment:
      BOT_TOKEN: ${BOT_TOKEN}
      BOT_CLIENT_ID: ${BOT_CLIENT_ID}
      BOT_DEBUG: ${BOT_DEBUG:-false}
      LLM_BASE_URL: ${LLM_BASE_URL:-}
      LLM_API_KEY: ${LLM_API_KEY:-}
      LLM_DEFAULT_MODEL: ${LLM_DEFAULT_MODEL:-}
      LLM_IMAGE_API_KEY: ${LLM_IMAGE_API_KEY:-}
      LLM_IMAGE_MODEL: ${LLM_IMAGE_MODEL:-dall-e-3}
      LAVALINK_HOST: lavalink
      LAVALINK_PORT: 2333
      LAVALINK_PASSWORD: ${LAVALINK_PASSWORD:-youshallnotpass}
      LAVALINK_LOCAL_NODE_COUNT: 1
    volumes:
      - ./music:/app/music
      - ./mygo-ave-video:/app/mygo-ave-video

  lavalink:
    image: ghcr.io/lavalink-devs/lavalink:4.2.2-alpine
    restart: unless-stopped
    environment:
      LAVALINK_SERVER_PASSWORD: ${LAVALINK_PASSWORD:-youshallnotpass}
    expose:
      - "2333"
    volumes:
      - ./application.yml:/opt/Lavalink/application.yml:ro

```
```bash
docker compose up -d
```

### Kubernetes

Rosetta supports automatic Lavalink node discovery via the Kubernetes Endpoints API. This is useful when running multiple Lavalink replicas behind a headless Service.

1. **Deploy Lavalink** as a `StatefulSet` or `Deployment` with a **headless Service** (e.g., `lavalink`).

2. **Deploy Rosetta** with the following environment variables:

   ```yaml
   env:
     - name: LAVALINK_DISCOVERY_MODE
       value: "k8s"
     - name: LAVALINK_K8S_NAMESPACE
       value: "default"
     - name: LAVALINK_K8S_SERVICE_NAME
       value: "lavalink"
     - name: LAVALINK_K8S_SERVICE_PORT
       value: "2333"
     - name: LAVALINK_PASSWORD
       value: "youshallnotpass"
   ```

3. **RBAC**: The Rosetta pod's service account needs permission to read Endpoints in the target namespace:

   ```yaml
   apiVersion: rbac.authorization.k8s.io/v1
   kind: Role
   metadata:
     name: rosetta-lavalink-reader
   rules:
     - apiGroups: [""]
       resources: ["endpoints"]
       verbs: ["get", "list", "watch"]
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: RoleBinding
   metadata:
     name: rosetta-lavalink-reader
   subjects:
     - kind: ServiceAccount
       name: rosetta
   roleRef:
     kind: Role
     name: rosetta-lavalink-reader
     apiGroup: rbac.authorization.k8s.io
   ```

Rosetta will automatically discover all Lavalink pod IPs and connect to each one. Use `!reload_nodes` or `/switchnode` to manage nodes at runtime.

### Local Development

#### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [FFmpeg](https://ffmpeg.org/) (for MyGO GIF generation)
- A running Lavalink instance (see `docker-compose.dev.yaml`)

#### Setup

1. **Start Lavalink** (two nodes for local dev):

   ```bash
   docker compose -f docker-compose.dev.yaml up -d
   ```

2. **Install dependencies**:

   ```bash
   uv sync
   ```

3. **Create your local environment file** (shell environment variables still take precedence):

   ```bash
   cp .env.example .env
   # Edit .env with your bot token, client ID, and optional integrations.
   ```

4. **Run the bot**:

   ```bash
   uv run python -m rosetta
   ```

---

## Tech Stack

- **Python 3.12** with [discord.py](https://github.com/Rapptz/discord.py)
- **Lavalink v4** via [lava-lyra](https://github.com/ParrotXray/lava-lyra) for music playback
- **OpenAI-compatible API** for LLM chat & image generation
- **Langfuse** for LLM observability & tracing
- **FFmpeg** + **ffmpeg-python** for GIF generation
- **Kubernetes** client for Lavalink node auto-discovery
- **uv** for dependency management
- **Docker** (Alpine-based) for deployment
