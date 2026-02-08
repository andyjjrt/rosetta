# Utility Commands

General-purpose commands for bot information and diagnostics.

## `/ping`

Check the bot's latency. If the bot is connected to a voice channel in the current guild, it shows the Lavalink node latency instead.

## `/version`

Show bot version information including:

- Rosetta version
- Python version
- discord.py version

**Admin view** (bot owner only) additionally shows:

- Guild / user / channel statistics
- System info (OS, platform)
- Loaded cogs and slash command count
- Lavalink node status, latency, and connection info

## `!guilds`

!!! info "Prefix Command"
    This is a prefix command (use `!guilds`, not `/guilds`). Restricted to the bot owner.

List all guilds the bot is currently in with an interactive paginated view.
