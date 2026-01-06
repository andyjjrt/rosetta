import discord
from discord import app_commands
from discord.ext import commands
from langfuse import get_client, openai

from ..utils.cog import Cog
from ..utils.config import LLMConfig
from ..utils.embeds import InfoEmbed
from ..utils.views.LLM import LLMView

client = openai.AsyncOpenAI(
    base_url=LLMConfig.BASE_URL,
    api_key=LLMConfig.API_KEY,
)

langfuse_client = get_client()

UPDATE_INTERVAL_SECONDS = 1
DISCORD_CHAR_LIMIT = 2000
SAFE_SPLIT_LIMIT = 1980


async def get_models_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    models_list = await client.models.list()
    models = [m.id for m in models_list.data]
    return [app_commands.Choice(name=m, value=m) for m in models if current in m][:25]


class LLM(Cog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)

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
    @app_commands.describe(prompt="Your prompt", model="Model to use")
    @app_commands.autocomplete(model=get_models_autocomplete)
    async def chat(
        self,
        interaction: discord.Interaction,
        prompt: str,
        model: str = None,
    ):
        if model is None:
            model = LLMConfig.get("DEFAULT_MODEL")
        await interaction.response.defer()

        user_id = str(interaction.user.id)
        with langfuse_client.start_as_current_span(
            name="discord-ask-command",
            input=prompt,
        ) as root_span:
            root_span.update_trace(
                user_id=user_id,
                metadata={
                    "discord_username": interaction.user.name,
                    "channel_id": str(interaction.channel.id),
                    "guild_id": str(interaction.guild.id)
                    if interaction.guild
                    else "DM",
                },
            )

            view = LLMView(model)
            message = await interaction.followup.send(view=view, wait=True)
            try:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant on Discord, skilled in formatting your output with markdown.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    stream=True,
                    stream_options={"include_usage": True}
                )

                async for chunk in stream:
                    await view.update_chunk(message, chunk)
                await view.end_chunk(message)

            except Exception as e:
                raise e

            root_span.update(output=view.full_response)
