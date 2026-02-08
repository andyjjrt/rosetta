# LLM Commands

Chat and image generation via an OpenAI-compatible API, with [Langfuse](https://langfuse.com/) observability.

All LLM commands are grouped under `/llm`.

## `/llm chat`

Chat with a language model. Supports text prompts and image attachments for vision models.

| Parameter | Description | Required |
|-----------|-------------|----------|
| `prompt` | Your text prompt | Yes (or `image`) |
| `image` | Image attachment for vision models | No |
| `model` | Model to use (owner only, autocomplete) | No |

- Responses are **streamed** in real-time and displayed with a live-updating embed.
- Non-owner users always use the configured `LLM_DEFAULT_MODEL`.
- The bot owner can select from all available models via autocomplete.
- All interactions are traced in **Langfuse** (if configured) with user ID, channel, and guild metadata.
- A **cancel** button is available during streaming.

## `/llm list`

List all available models from the configured LLM provider.

!!! info
    This command is available to all users, but model selection in `/llm chat` is restricted to the bot owner.

## `/llm image`

Generate an image from a text prompt.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `prompt` | Description of the image to generate | — |
| `size` | Image size (`720x480`, `1280x720`, `1024x1024`, `1920x1080`) | `1280x720` |
| `num_inference_steps` | Number of inference steps | `9` |
| `true_cfg_scale` | CFG scale | `4.0` |
| `seed` | Random seed for reproducibility | Random |

!!! warning
    This command is currently restricted to the bot owner.

## Install Context

All `/llm` commands support both **guild** and **user** install contexts, meaning they work in:

- Guild channels
- DM channels
- Group DMs / private channels
