# Music Commands

Powered by [Lavalink](https://github.com/lavalink-devs/Lavalink) via [lava_lyra](https://github.com/ParrotXray/lava-lyra). Supports Kubernetes-based Lavalink node discovery for multi-node setups.

## `/play`

Play a YouTube URL (supports playlists).

| Parameter | Description | Required |
|-----------|-------------|----------|
| `url` | YouTube video or playlist URL | Yes |
| `loop` | Loop mode: `Off`, `One`, or `Queue` | No |
| `shuffle` | Shuffle the playlist after adding | No |
| `top` | Add to the top of the queue | No |
| `node_name` | Specify a Lavalink node to use | No |

The bot will join your current voice channel automatically if not already connected.

## `/search`

Search YouTube and select a track interactively.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `keyword` | Search term | Yes |

Returns an interactive view with search results to choose from.

## `/nowplaying`

Show the currently playing track with a progress bar and queue controls.

## `/skip`

Skip to the next song in the queue. If the queue is empty, the bot leaves the channel.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `ephemeral` | Hide the response | No |

## `/shuffle`

Shuffle the current queue.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `ephemeral` | Hide the response | No |

## `/loop`

Set the loop mode.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `loop` | `Off`, `One`, or `Queue` | Yes |

## `/leave`

Disconnect the bot from the voice channel and clear the queue.

## `/switchnode`

Switch playback to a different Lavalink node. Useful in multi-node deployments.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `node_name` | The target Lavalink node (autocomplete supported) | Yes |

## Admin Commands

These prefix commands are restricted to the bot owner:

| Command | Description |
|---------|-------------|
| `!reload_nodes` | Remove all Lavalink nodes and re-register them |
