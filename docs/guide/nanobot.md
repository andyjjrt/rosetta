# Nanobot Setup

Nanobot is disabled by default. Enabling its cog is only the first step: you must also provide its agent configuration, enable the private Rosetta MCP endpoint, copy a managed MCP API key into the Nanobot config, and grant each Discord server access through `/setting nanobot`.

## Prerequisites

Before enabling Nanobot, make sure that:

- Discord's privileged **Message Content Intent** is enabled in the Developer Portal.
- Rosetta has working Lavalink music playback. Nanobot's MCP tools expose music `search` and `play`.
- `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_DEFAULT_MODEL` point to a working OpenAI-compatible provider.
- You can run `/setting nanobot` as a server administrator.

## Create the agent configuration

Copy the committed template to an operator-owned, untracked path:

```bash
cp nanobot.config.example.json nanobot.config.json
```

The template reads provider, model, workspace, MCP URL, and managed MCP API key values from environment variables. Its important security defaults are:

- file access is restricted to `NANOBOT_WORKSPACE`;
- shell execution and web access are disabled;
- only the loopback `127.0.0.1/32` network is allowlisted;
- only Rosetta's `search` and `play` MCP tools are enabled.

Do not commit `nanobot.config.json`, put secrets directly in it, broaden the workspace to the repository root, or replace the loopback MCP URL with `0.0.0.0`.

## Configure the environment

Set these values in `.env` when running from source:

```dotenv
COG_NANOBOT_DISABLE=false
NANOBOT_CONFIG_PATH=nanobot.config.json
NANOBOT_POLICY_PATH=.data/nanobot/guild-policies.json
NANOBOT_MAX_CONCURRENT_RUNS=3
NANOBOT_WORKSPACE=.data/nanobot/workspace
SETTING_DATABASE_PATH=.data/settings.sqlite3

LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=replace-with-provider-key
LLM_DEFAULT_MODEL=replace-with-model-name

MCP_ENABLED=true
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_PATH=/mcp
MCP_ALLOWED_HOSTS='["127.0.0.1","localhost"]'
```

`NANOBOT_CONFIG_PATH` must exist and be readable when the cog is enabled. The policy file and workspace directories are created as they are used. Keep both under `.data/` so they remain separate from source code and secrets.

Bootstrap managed MCP access by starting Rosetta with `MCP_ENABLED=true` and a persistent `SETTING_DATABASE_PATH`, then running `/setting mcp create <name>` as the bot owner. Copy the one-time plaintext key from that response into `nanobot.config.json` as `NANOBOT_ROSETTA_MCP_API_KEY`; Rosetta stores only a hash and cannot reveal the key again.

## Docker Compose

For Compose, keep `nanobot.config.json` beside the Compose files and start Rosetta with the opt-in overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.nanobot.yaml up -d
```

The overlay:

- mounts `nanobot.config.json` read-only at `/app/nanobot.config.json`;
- persists the policy and workspace under `/app/.data/nanobot/`;
- enables Nanobot and the loopback MCP endpoint;
- passes the existing LLM provider settings through to the agent configuration.

Provide `SETTING_DATABASE_PATH`, `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_DEFAULT_MODEL` in the Compose environment before starting the service.

## Configure a server's guild policy

Guild access is deny-by-default. An enabled cog does not answer anywhere until an administrator configures the server:

1. Run `/setting nanobot` in the Discord server.
2. Select **Enable**.
3. Use **Add text channels** to allow one or more channels.
4. Mention Rosetta in an allowed channel to verify the policy.

The settings response is ephemeral. Only administrators can open it, and only the administrator who opened that view can use its controls. **Disable** stops Nanobot for the whole server without deleting its allowed-channel list. **Remove text channels** revokes individual channels.

Threads inherit the policy of their parent text channel but retain separate Nanobot conversation history. DMs, bot or webhook messages, disabled servers, disabled channels, and ordinary replies without a Rosetta mention are ignored.

Rosetta writes the policy atomically to `NANOBOT_POLICY_PATH`. A generated policy has this shape:

```json
{
  "version": 1,
  "guilds": {
    "123456789012345678": {
      "enabled": true,
      "channel_ids": ["234567890123456789"]
    }
  }
}
```

Guild and channel IDs are decimal strings. Prefer `/setting nanobot` instead of editing this file by hand, especially while Rosetta is running. A missing file is treated as an empty policy where every server is disabled; malformed JSON or an invalid schema makes policy lookups fail closed.

## Troubleshooting

- **`NANOBOT_CONFIG_PATH` startup error:** confirm that the copied JSON file exists and is readable from the process or container.
- **Mentions do nothing:** confirm Message Content Intent, then run `/setting nanobot` and check that both the server and parent text channel are enabled.
- **HTTP 401 from MCP:** no managed API key exists yet, or the Nanobot client key was copied incorrectly/revoked/rotated. Run `/setting mcp create <name>` as the bot owner, copy the one-time key into `nanobot.config.json`, and restart the client if needed.
- **MCP startup rejects allowed hosts:** keep `MCP_ALLOWED_HOSTS` as a single-quoted JSON list in `.env`.
- **Local URL or SSRF rejection:** keep the client URL on `127.0.0.1` and retain `127.0.0.1/32` in `ssrfWhitelist`.
