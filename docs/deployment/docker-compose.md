# Docker Compose

The simplest way to deploy Rosetta in production.

## Setup

Create a `docker-compose.yml` in your project directory:

```yaml
services:
  rosetta:
    image: ghcr.io/andyjjrt/rosetta:latest
    restart: unless-stopped
    depends_on:
      lavalink:
        condition: service_started
    environment:
      - BOT_TOKEN=your-bot-token
      - BOT_CLIENT_ID=your-client-id
      - LLM_BASE_URL=https://api.example.com/v1
      - LLM_API_KEY=your-api-key
      - LLM_DEFAULT_MODEL=gpt-4
      - LAVALINK_HOST=lavalink
      - LAVALINK_PORT=2333
      - LAVALINK_PASSWORD=youshallnotpass
      - LAVALINK_LOCAL_NODE_COUNT=1
    volumes:
      - ./music:/app/music
      - ./mygo-ave-video:/app/mygo-ave-video

  lavalink:
    image: ghcr.io/lavalink-devs/lavalink:4.2.2-alpine
    restart: unless-stopped
    environment:
      - LAVALINK_SERVER_PASSWORD=youshallnotpass
    expose:
      - "2333"
    volumes:
      - ./application.yml:/opt/Lavalink/application.yml:ro
```

## Lavalink Configuration

Create an `application.yml` for Lavalink:

```yaml
server:
  port: 2333
  address: 0.0.0.0

plugins:
  youtube:
    enabled: true
    allowSearch: true
    allowDirectVideoIds: true
    allowDirectPlaylistIds: true
    clients:
      - MUSIC
      - ANDROID_VR
      - WEB
      - WEBEMBEDDED

lavalink:
  plugins:
    - dependency: "dev.lavalink.youtube:youtube-plugin:1.18.1"
      repository: "https://maven.lavalink.dev/releases"
      snapshot: false
  server:
    password: "youshallnotpass"
    sources:
      youtube: false
```

## Run

```bash
docker compose up -d
```

## Updating

```bash
docker compose pull
docker compose up -d
```

## Viewing Logs

```bash
# All services
docker compose logs -f

# Rosetta only
docker compose logs -f rosetta
```

## NodeLink Alternative

The root `docker-compose.yml` starts Lavalink, not NodeLink. If you prefer to run Rosetta with NodeLink, you can replace the Lavalink service with a NodeLink container.

Note the port: Rosetta connects to the `nodelink` service over the Docker overlay network, so it uses the **container port** (3000), not the host-mapped port (2333). The host mapping `2333:3000` is only for external access.

```yaml
services:
  rosetta:
    image: ghcr.io/andyjjrt/rosetta:latest
    restart: unless-stopped
    depends_on:
      nodelink:
        condition: service_started
    environment:
      - BOT_TOKEN=your-bot-token
      - BOT_CLIENT_ID=your-client-id
      - LLM_BASE_URL=https://api.example.com/v1
      - LLM_API_KEY=your-api-key
      - LLM_DEFAULT_MODEL=gpt-4
      - LAVALINK_HOST=nodelink
      - LAVALINK_PORT=3000
      - LAVALINK_PASSWORD=youshallnotpass
      - LAVALINK_LOCAL_NODE_COUNT=1
    volumes:
      - ./music:/app/music
      - ./mygo-ave-video:/app/mygo-ave-video

  nodelink:
    image: performanc/nodelink:3.6.0
    restart: unless-stopped
    ports:
      - "2333:3000"
    environment:
      NODELINK_SERVER_HOST: "0.0.0.0"
      NODELINK_SERVER_PORT: "3000"
      NODELINK_SERVER_PASSWORD: "youshallnotpass"
```
