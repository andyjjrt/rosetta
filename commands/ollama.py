from discord import (
    Bot,
    ApplicationContext,
    AutocompleteContext,
    SlashCommandGroup,
    SlashCommandOptionType,
    option,
)
from discord.ext import commands
from utils.embeds import SuccessEmbed, InfoEmbed
from ollama import list, pull, chat
from utils import split_markdown


class Ollama(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    ollama = SlashCommandGroup("ollama")

    @staticmethod
    def get_models(self: AutocompleteContext):
        text = self.options["model"]
        models = [f"{m.model}" for m in list().models]
        return [m for m in models if text in m][:25]

    @ollama.command(description="List all models")
    @commands.is_owner()
    async def list(self, ctx: ApplicationContext):
        res = list()
        embed = InfoEmbed(
            ctx.user,
            "\n".join(
                [f"- {m.model} `{(m.size / (1024**3)):.2f}GB`" for m in res.models]
            ),
        )
        await ctx.respond(embed=embed)

    @ollama.command(description="Pull model")
    @commands.is_owner()
    @option(
        "model",
        type=SlashCommandOptionType.string,
    )
    async def pull(self, ctx: ApplicationContext, model: str):
        pull(model=model, stream=False)
        await ctx.respond(
            embed=SuccessEmbed(ctx.user, f"Pulling `{model}`, come back later")
        )

    @ollama.command(description="Chat with a model")
    @option(
        "content",
        type=SlashCommandOptionType.string,
    )
    @option(
        "model",
        type=SlashCommandOptionType.string,
        autocomplete=get_models,
    )
    async def chat(self, ctx: ApplicationContext, content: str, model: str):
        await ctx.defer()
        message = {"role": "user", "content": content}
        result = chat(model=model, messages=[message])
        content = split_markdown(result.message.content)
        message = await ctx.respond(content[0])
        if len(content) > 1:
            channel = message.channel
            for c in content[1:]:
                await channel.send(c)
