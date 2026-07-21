# Repository Guide

## Sources of truth

- This is a Python 3.12 `uv` project. Treat `pyproject.toml` plus `uv.lock` as authoritative; `requirement.txt` is an unused, stale compile output.
- Prefer executable config over the README. Runtime uses `lava-lyra`, not Pomice; Lavalink is the media backend.
- Runtime settings are defined in `rosetta/utils/config.py`. Pydantic settings are instantiated at import time and load `.env` from the current working directory; exported variables and container-provided environment values take precedence.

## Commands

```bash
uv sync
uv run python -m rosetta

# Non-mutating verification
uv run ruff check .
uv run ruff format --check .

# Focused verification
uv run ruff check path/to/file.py
uv run ruff format --check path/to/file.py

# Match docs CI; MkDocs is not installed by plain `uv sync`
uv sync --group docs
uv run mkdocs build --strict
```

- Pre-commit runs Ruff with `--fix --extend-select I`, then formats. `uv run pre-commit run --all-files` mutates files; use the non-mutating commands above when reviewing only.
- There is no test suite, test dependency, type-checker config, or quality job in CI. Release CI only runs for `v*` tags and builds/publishes the Docker image; docs CI builds strictly on tags or manual dispatch.
- The Docker build deliberately uses `uv sync --frozen --no-dev`; keep lockfile and manifest synchronized.

## Runtime wiring

- `rosetta/__main__.py` is the composition root: logging, intents, global command errors, emoji fetch, cog registration, command sync, and `bot.run`. A new cog must be imported and added to `setup_hook`; optional cogs also need a `COG_<NAME>_DISABLE` setting in `rosetta/utils/config.py`.
- Cogs should inherit `rosetta.utils.cog.Cog`, not `discord.ext.commands.Cog`. The custom base installs the app-command interaction check and places timing plus the contextual logger in `interaction.extras`.
- `rosetta/commands/__init__.py` eagerly imports every cog. `commands/llm.py` constructs chat and image clients at import time, so startup needs both `LLM_API_KEY` and `LLM_IMAGE_API_KEY`, or an `OPENAI_API_KEY` fallback; `COG_LLM_DISABLE=true` does not avoid those imports.
- `Mygo` eagerly opens `mygo-ave-video/data.json` when its cog is constructed. Run `bash scripts/mygo-ave-preprocess.sh` to populate the ignored video/data directory, or set `COG_MYGO_DISABLE=true`; FFmpeg/ffprobe are required for GIF generation.
- Local media-node startup is `docker compose -f docker-compose.dev.yaml up -d`. It starts two Lavalink nodes on 2333 and 2334. `LAVALINK_LOCAL_NODE_COUNT` controls sequential local endpoints and production Compose sets it to one.
- Kubernetes discovery in `rosetta/utils/nodepool.py` silently falls back to local endpoints when discovery fails or returns none; do not assume `LAVALINK_DISCOVERY_MODE=k8s` guarantees a Kubernetes connection.

## Feature boundaries

- Music orchestration lives in `commands/music.py`; queue semantics and live node migration live in `utils/player.py`; discovery/connection ownership lives in `utils/nodepool.py`.
- LLM streaming state, pagination, cancellation, and metrics belong to `utils/views/LLM.py`; `commands/llm.py` feeds API chunks into that view.
- Discord application emojis are fetched in `on_ready` and stored in `EmojiConfig`; embeds/views expect the names listed in `.env.example` and tolerate missing names only as empty strings.
- `mygo-ave-video/`, `.env`, `.omo/`, logs, and local media are ignored runtime data. Do not treat them as reproducible repository fixtures or include their contents in changes.
