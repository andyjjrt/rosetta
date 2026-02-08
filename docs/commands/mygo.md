# MyGO Commands

Generate GIFs from [MyGO!!!!!](https://en.wikipedia.org/wiki/BanG_Dream!_It%27s_MyGO!!!!!) anime scenes.

## `/mygo`

Search for a scene by subtitle text and generate an animated GIF.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `text` | Scene to search for (autocomplete by subtitle) | — |
| `resolution` | Output resolution: `240p`, `360p`, or `720p` | `240p` |
| `ephemeral` | Hide the response (only you can see it) | `false` |

### How It Works

1. Type `/mygo` and start typing in the `text` field.
2. The bot autocompletes matching scenes from the preprocessed subtitle data.
3. Select a scene — the bot generates a GIF using FFmpeg with optimized palettes.
4. The GIF is sent as a file attachment.

### Setup

Before using this command, you need to preprocess the video data:

```bash
bash scripts/mygo-ave-preprocess.sh
```

This creates the `mygo-ave-video/` directory with episode videos and a `data.json` metadata file.

### Install Context

This command supports both **guild** and **user** install contexts, meaning it works in guild channels, DMs, and group DMs.
