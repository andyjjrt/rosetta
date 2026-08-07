# Configuration

All configuration uses **environment variables**. For local development, Rosetta also loads `.env` from the current working directory; exported variables take precedence over values in that file.

## Bot Settings

| Variable | Description | Required |
|----------|-------------|----------|
| `BOT_TOKEN` | Discord bot token | Yes |
| `BOT_CLIENT_ID` | Discord application client ID | Yes |
| `BOT_DEBUG` | Enable debug logging (`true`/`false`) | No |

## LLM Settings

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_BASE_URL` | OpenAI-compatible API base URL | For LLM features |
| `LLM_API_KEY` | API key for the LLM provider | For LLM features |
| `LLM_DEFAULT_MODEL` | Default model for `/llm chat` | For LLM features |
| `LLM_IMAGE_API_KEY` | API key for image generation (can differ from chat key) | For image gen |
| `LLM_IMAGE_MODEL` | Model for `/llm image` (default: `dall-e-3`) | No |

## Lavalink Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `LAVALINK_DISCOVERY_MODE` | `local` or `k8s` for Kubernetes node discovery | `local` |
| `LAVALINK_HOST` | Lavalink host | `127.0.0.1` |
| `LAVALINK_PORT` | Lavalink port | `2333` |
| `LAVALINK_PASSWORD` | Lavalink password | `youshallnotpass` |
| `LAVALINK_LOCAL_NODE_COUNT` | Number of sequential local nodes starting at `LAVALINK_PORT` (default: `2`, production: `1`, ignored in `k8s` mode) | `2` |

### Kubernetes Discovery

These are only needed when `LAVALINK_DISCOVERY_MODE=k8s`:

| Variable | Description | Default |
|----------|-------------|---------|
| `LAVALINK_K8S_NAMESPACE` | Kubernetes namespace for Lavalink service discovery | `default` |
| `LAVALINK_K8S_SERVICE_NAME` | Kubernetes service name for Lavalink | `lavalink` |
| `LAVALINK_K8S_SERVICE_PORT` | Kubernetes service port for Lavalink | `2333` |

## Langfuse Settings

| Variable | Description | Required |
|----------|-------------|----------|
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | For tracing |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | For tracing |
| `LANGFUSE_HOST` | Langfuse host URL | For tracing |

## Nanobot Settings

Nanobot is disabled by default and requires both an agent configuration file and a per-server guild policy. See [Nanobot Setup](nanobot.md) for the complete setup and Discord administration workflow.

| Variable | Description | Default |
|----------|-------------|---------|
| `COG_NANOBOT_DISABLE` | Disable the Nanobot cog | `true` |
| `NANOBOT_CONFIG_PATH` | Readable Nanobot agent configuration file | `.data/nanobot/config.json` |
| `NANOBOT_POLICY_PATH` | Persisted guild/channel allow policy | `.data/nanobot/guild-policies.json` |
| `NANOBOT_MAX_CONCURRENT_RUNS` | Maximum concurrent Nanobot turns | `3` |
| `NANOBOT_WORKSPACE` | Agent file-tool workspace used by `nanobot.config.json` | `.data/nanobot/workspace` |

Nanobot's Rosetta tools require the private MCP endpoint:

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_ENABLED` | Enable the private MCP endpoint | `false` |
| `MCP_HOST` | MCP bind address | `127.0.0.1` |
| `MCP_PORT` | MCP listener port | `8000` |
| `MCP_PATH` | Streamable HTTP mount path | `/mcp` |
| `SETTING_DATABASE_PATH` | Managed settings SQLite database path for MCP API keys | `.data/settings.sqlite3` |
| `MCP_ALLOWED_HOSTS` | Accepted HTTP Host values as a quoted JSON list | `["127.0.0.1","localhost"]` |

## Example `.env` File

Copy `.env.example` to `.env`, then replace the placeholder values:

```bash
# Bot
BOT_TOKEN=your-bot-token
BOT_CLIENT_ID=your-client-id
BOT_DEBUG=false

# Lavalink
LAVALINK_HOST=127.0.0.1
LAVALINK_PORT=2333
LAVALINK_PASSWORD=youshallnotpass
LAVALINK_LOCAL_NODE_COUNT=2

# LLM
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=your-api-key
LLM_DEFAULT_MODEL=gpt-4

# Langfuse (optional)
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://langfuse.example.com
```
