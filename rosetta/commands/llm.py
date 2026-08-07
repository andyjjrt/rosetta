import discord
from discord import app_commands
from discord.ext import commands

from ..utils.cog import Cog
from ..utils.config import LLMConfig, SettingConfig
from ..utils.embeds import InfoEmbed
from ..utils.langfuse import TraceRequest, create_async_openai, trace_request
from ..utils.llm_model_access import LlmModelAccessRepository
from ..utils.views.Image import ImageView
from ..utils.views.LLM import LLMView

client = create_async_openai(
    base_url=LLMConfig.BASE_URL,
    api_key=LLMConfig.API_KEY,
)

image_client = create_async_openai(
    base_url=LLMConfig.BASE_URL,
    api_key=LLMConfig.API_KEY,
)

UPDATE_INTERVAL_SECONDS = 1
DISCORD_CHAR_LIMIT = 2000
SAFE_SPLIT_LIMIT = 1980


class LLM(Cog):
    def __init__(
        self,
        bot: commands.Bot,
        *,
        model_access_repository: LlmModelAccessRepository | None = None,
    ) -> None:
        super().__init__(bot)
        self._model_access_repository = (
            model_access_repository
            or LlmModelAccessRepository(SettingConfig.DATABASE_PATH)
        )

    async def can_select_model(self, interaction: discord.Interaction) -> bool:
        if await self.bot.is_owner(interaction.user):
            return True
        return await self._model_access_repository.is_allowed(interaction.user.id)

    llm_group = app_commands.Group(
        name="llm",
        description="LLM commands",
        allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
        allowed_contexts=app_commands.AppCommandContext(
            guild=True, dm_channel=True, private_channel=True
        ),
    )

    @llm_group.command(name="list", description="List all models")
    async def list_models(self, interaction: discord.Interaction):
        res = await client.models.list()
        embed = InfoEmbed(
            self.bot.user,
            "\n".join([f"- {m.id}" for m in res.data]),
        )
        await interaction.response.send_message(embed=embed)

    @llm_group.command(name="chat", description="Chat with a model")
    @app_commands.describe(
        prompt="Your prompt",
        image="Image attachment for vision models",
        model="Model to use (owner or allowlisted users)",
    )
    async def chat(
        self,
        interaction: discord.Interaction,
        prompt: str = None,
        image: discord.Attachment = None,
        model: str = None,
    ):
        # Validate that at least prompt or image is provided
        if not prompt and image is None:
            await interaction.response.send_message(
                "Please provide a prompt or an image.", ephemeral=True
            )
            return

        if model is None or not await self.can_select_model(interaction):
            model = LLMConfig.DEFAULT_MODEL
        await interaction.response.defer()

        # Build user message content - supports multimodal (text + image)
        if image is not None:
            # Validate image attachment
            if not image.content_type or not image.content_type.startswith("image/"):
                await interaction.followup.send(
                    "The attachment must be an image file.", ephemeral=True
                )
                return
            user_content = [
                {"type": "text", "text": prompt or ""},
                {"type": "image_url", "image_url": {"url": image.url}},
            ]
        else:
            user_content = prompt

        user_id = str(interaction.user.id)
        with trace_request(
            TraceRequest(
                name="discord-ask-command",
                input=prompt,
                user_id=user_id,
                metadata={
                    "discord_username": interaction.user.name,
                    "channel_id": str(interaction.channel.id),
                    "guild_id": str(interaction.guild.id)
                    if interaction.guild
                    else "DM",
                    "has_image": image is not None,
                },
            )
        ) as root_span:
            view = LLMView(
                model, prompt=prompt or "", image_url=image.url if image else None
            )
            message = await interaction.followup.send(
                view=view, wait=True, allowed_mentions=discord.AllowedMentions.none()
            )
            try:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant on Discord, skilled in formatting your output with markdown.",
                        },
                        {"role": "user", "content": user_content},
                    ],
                    stream=True,
                    stream_options={"include_usage": True},
                )

                async for chunk in stream:
                    if view.cancelled:
                        await stream.close()
                        break
                    await view.update_chunk(message, chunk)
                await view.end_chunk(message)

            except Exception as e:
                raise e

            if root_span is not None:
                root_span.update(output=view.full_response)

    @chat.autocomplete("model")
    async def model_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if not await self.can_select_model(interaction):
            default_model = LLMConfig.DEFAULT_MODEL
            if default_model and current.lower() in default_model.lower():
                return [app_commands.Choice(name=default_model, value=default_model)]
            return []

        models_list = await client.models.list()
        models = [model.id for model in models_list.data]
        current_lower = current.lower()
        return [
            app_commands.Choice(name=model, value=model)
            for model in models
            if current_lower in model.lower()
        ][:25]

    @llm_group.command(
        name="image",
        description="Generate an image from a prompt [Admin only currently]",
    )
    @app_commands.describe(
        prompt="Description of the image to generate",
        size="Image size",
        num_inference_steps="Number of inference steps (default: 9)",
        true_cfg_scale="CFG scale (default: 4.0)",
        seed="Random seed for reproducibility",
    )
    @app_commands.choices(
        size=[
            app_commands.Choice(name="720x480", value="720x480"),
            app_commands.Choice(name="1280x720", value="1280x720"),
            app_commands.Choice(name="1024x1024", value="1024x1024"),
            app_commands.Choice(name="1920x1080", value="1920x1080"),
        ],
    )
    async def image_gen(
        self,
        interaction: discord.Interaction,
        prompt: str,
        size: str = "1280x720",
        num_inference_steps: int = 9,
        true_cfg_scale: float = 4.0,
        seed: int = None,
    ):
        await interaction.response.defer()
        if not await self.bot.is_owner(interaction.user):
            raise commands.CommandError("The command is not available now")

        view = ImageView(
            model=LLMConfig.IMAGE_MODEL,
            prompt=prompt,
            size=size,
            num_inference_steps=num_inference_steps,
            true_cfg_scale=true_cfg_scale,
            seed=seed,
        )
        message = await interaction.followup.send(view=view, wait=True)

        extra_body = {
            "num_inference_steps": num_inference_steps,
            "true_cfg_scale": true_cfg_scale,
        }
        if seed is not None:
            extra_body["seed"] = seed

        user_id = str(interaction.user.id)
        with trace_request(
            TraceRequest(
                name="discord-image-gen-command",
                input=prompt,
                user_id=user_id,
                metadata={
                    "discord_username": interaction.user.name,
                    "channel_id": str(interaction.channel.id),
                    "guild_id": str(interaction.guild.id)
                    if interaction.guild
                    else "DM",
                    "model": LLMConfig.IMAGE_MODEL,
                    "size": size,
                    "num_inference_steps": num_inference_steps,
                    "true_cfg_scale": true_cfg_scale,
                    "seed": seed,
                },
            )
        ) as root_span:
            try:
                response = await image_client.images.generate(
                    model=LLMConfig.IMAGE_MODEL,
                    prompt=prompt,
                    size=size,
                    extra_body=extra_body,
                )

                image_b64 = response.data[0].b64_json
                view.set_image(image_b64)

                await view.update_result(message)
                if root_span is not None:
                    root_span.update(output="Image generated successfully")

            except Exception as e:
                self._logger.error(e)
                view.set_error(str(e))
                await view.update_result(message)
                if root_span is not None:
                    root_span.update(output=f"Error: {str(e)}")
