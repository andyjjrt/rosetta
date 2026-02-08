# Rosetta

A Discord bot with music playback, LLM chat, image generation, and MyGO anime GIF features. Built with [discord.py](https://github.com/Rapptz/discord.py) and [Lavalink](https://github.com/lavalink-devs/Lavalink).

## Features

### 🎵 Music

Powered by [Lavalink](https://github.com/lavalink-devs/Lavalink) via [Pomice](https://github.com/cloudwithax/pomice). Supports Kubernetes-based Lavalink node discovery for multi-node setups.

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
| `LAVALINK_K8S_NAMESPACE` | Kubernetes namespace for Lavalink service discovery |
| `LAVALINK_K8S_SERVICE_NAME` | Kubernetes service name for Lavalink |
| `LAVALINK_K8S_SERVICE_PORT` | Kubernetes service port for Lavalink |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host URL |

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
    environment:
      - BOT_TOKEN=your-bot-token
      - BOT_CLIENT_ID=your-client-id
      - LLM_BASE_URL=https://api.example.com/v1
      - LLM_API_KEY=your-api-key
      - LLM_DEFAULT_MODEL=gpt-4
      - LAVALINK_HOST=lavalink
      - LAVALINK_PORT=2333
      - LAVALINK_PASSWORD=youshallnotpass
    volumes:
      - ./music:/app/music
      - ./mygo-ave-video:/app/mygo-ave-video

  lavalink:
    image: ghcr.io/lavalink-devs/lavalink:4-alpine
    restart: unless-stopped
    environment:
      - _JAVA_OPTIONS=-Xmx6G
    volumes:
      - ./application.yml:/opt/Lavalink/application.yml
    ports:
      - "2333:2333"
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

3. **Set environment variables** (or create a `.env` file):

   ```bash
   export BOT_TOKEN=your-bot-token
   export BOT_CLIENT_ID=your-client-id
   export BOT_DEBUG=true
   export LAVALINK_HOST=127.0.0.1
   export LAVALINK_PORT=2333
   export LAVALINK_PASSWORD=youshallnotpass
   # LLM / Langfuse variables as needed
   ```

4. **Run the bot**:

   ```bash
   uv run python -m rosetta
   ```

---

## Tech Stack

- **Python 3.12** with [discord.py](https://github.com/Rapptz/discord.py)
- **Lavalink v4** via [Pomice](https://github.com/cloudwithax/pomice) for music playback
- **OpenAI-compatible API** for LLM chat & image generation
- **Langfuse** for LLM observability & tracing
- **FFmpeg** + **ffmpeg-python** for GIF generation
- **Kubernetes** client for Lavalink node auto-discovery
- **uv** for dependency management
- **Docker** (Alpine-based) for deployment