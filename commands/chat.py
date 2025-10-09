import time
import discord
from langfuse import get_client, openai
from openai.types.completion_usage import CompletionUsage
from discord.ext import commands
from utils.embeds import LLMPerformanceEmbed, InfoEmbed
from utils.config import LLM as LLMConfig

client = openai.AsyncOpenAI(
    base_url=LLMConfig.get("BASE_URL"),
    api_key=LLMConfig.get("API_KEY"),
)

langfuse_client = get_client()

UPDATE_INTERVAL_SECONDS = 1
DISCORD_CHAR_LIMIT = 2000
SAFE_SPLIT_LIMIT = 1980


async def get_models(ctx: discord.AutocompleteContext):
    text = ctx.options["model"]
    if await ctx.bot.is_owner(ctx.interaction.user):
        models_list = await client.models.list()
        models = [m.id for m in models_list.data]
    else:
        models = [LLMConfig.get("DEFAULT_MODEL")]
    return [m for m in models if text in m][:25]


def find_best_split_position(text: str, max_len: int) -> int:
    """
    Finds the best position to split text to respect paragraphs, lines, and words.
    Searches backwards from the max_len point.
    """
    if len(text) <= max_len:
        return len(text)

    # 1. Try to find a paragraph break (double newline)
    try:
        # Search backwards from the max_len position
        pos = text.rindex("\n\n", 0, max_len)
        return pos
    except ValueError:
        pass  # Not found

    # 2. If no paragraph break, try a line break (single newline)
    try:
        pos = text.rindex("\n", 0, max_len)
        return pos
    except ValueError:
        pass  # Not found

    # 3. If no newline, try to find the last space to not break a word
    try:
        pos = text.rindex(" ", 0, max_len)
        return pos
    except ValueError:
        pass  # Not found

    # 4. If all else fails, force a hard cut at the safe limit
    return max_len


class LLM(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.response_queue = {}

    llm = discord.SlashCommandGroup(
        "llm",
        integration_types=set(
            [
                discord.IntegrationType.user_install,
                discord.IntegrationType.guild_install,
            ]
        ),
    )

    @llm.command(description="List all models")
    async def list(self, ctx: discord.ApplicationContext):
        res = await client.models.list()
        embed = InfoEmbed(
            self.bot.user,
            "\n".join([f"- {m.id}" for m in res.data]),
        )
        await ctx.respond(embed=embed)

    @llm.command(
        description="Chat with a model",
    )
    @discord.option(
        "prompt",
        type=discord.SlashCommandOptionType.string,
    )
    @discord.option(
        "model",
        type=discord.SlashCommandOptionType.string,
        autocomplete=get_models,
        required=False,
        default=LLMConfig.get("DEFAULT_MODEL"),
    )
    async def chat(
        self,
        ctx: discord.ApplicationContext,
        prompt: str,
        model: str,
    ):
        await ctx.defer()

        user_id = str(ctx.author.id)
        with langfuse_client.start_as_current_span(
            name="discord-ask-command",
            input=prompt,
        ) as root_span:
            root_span.update_trace(
                user_id=user_id,
                metadata={
                    "discord_username": ctx.author.name,
                    "channel_id": str(ctx.channel.id),
                    "guild_id": str(ctx.guild.id) if ctx.guild else "DM",
                },
            )

            response_messages = []
            current_message_content = ""
            full_response = ""
            start_time, first_token_time, end_time = None, None, None

            initial_message = await ctx.respond(f"🧠 Thinking with `{model}`...")
            response_messages.append(initial_message)
            last_update_time = time.time()

            start_time = time.time()
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
                    stream_options={"include_usage": True},
                )

                usage = None

                async for chunk in stream:
                    content = chunk.choices[0].delta.content
                    usage = chunk.usage
                    if first_token_time is None and content:
                        first_token_time = time.time()

                    if content:
                        current_message_content += content
                        full_response += content  # Keep a full copy for logging
                        # ... (Smart splitting and periodic update logic is unchanged) ...
                        if len(current_message_content) > SAFE_SPLIT_LIMIT:
                            split_pos = find_best_split_position(
                                current_message_content, SAFE_SPLIT_LIMIT
                            )
                            text_to_send, carry_over_text = (
                                current_message_content[:split_pos],
                                current_message_content[split_pos:],
                            )
                            await response_messages[-1].edit(
                                content=text_to_send.strip()
                            )
                            response_messages.append(await ctx.send("..."))
                            current_message_content = carry_over_text.lstrip()
                            last_update_time = time.time()

                        if time.time() - last_update_time >= UPDATE_INTERVAL_SECONDS:
                            if current_message_content:
                                await response_messages[-1].edit(
                                    content=current_message_content + " █"
                                )
                                last_update_time = time.time()

                end_time = time.time()

            except Exception as e:
                end_time = time.time()  # Log end time even on failure
                error_message = f"An unexpected error occurred: {e}"
                print(f"Error during stream for prompt '{prompt}': {error_message}")

                if response_messages:
                    await response_messages[-1].edit(content=error_message)
                return

            ttft, tps, completion_tokens = 0.0, 0.0, 0
            if usage:
                completion_tokens = usage.completion_tokens
            if start_time and first_token_time:
                ttft = first_token_time - start_time
            if first_token_time and end_time:
                generation_time = end_time - first_token_time
                if generation_time > 0 and completion_tokens > 1:
                    tps = (completion_tokens - 1) / generation_time

            stats_text = (
                f"\n\n"
                f"-# {model} • {tps:.2f} tps • TTFT: {ttft:.2f}s • Tokens: {completion_tokens}"
            )
            final_content = current_message_content.strip()
            # 3. Handle the final message edit
            if final_content:
                # Check if appending the stats would exceed Discord's character limit
                if len(final_content) + len(stats_text) > DISCORD_CHAR_LIMIT:
                    # If it's too long, edit the last message with just the content...
                    await response_messages[-1].edit(content=final_content)
                    # ...and send the stats in a new, separate message.
                    await ctx.send(stats_text.strip())
                else:
                    # If it fits, combine them and edit the last message.
                    final_combined_content = final_content + stats_text
                    await response_messages[-1].edit(content=final_combined_content)
            else:
                # Handle the case where the response was empty but we still want to clean up
                if (
                    len(response_messages) > 1
                    and response_messages[-1].content == "..."
                ):
                    await response_messages[-1].delete()
                else:
                    # Edit the very first message if there was no output at all
                    await response_messages[0].edit(
                        content="*No response was generated.*"
                    )

            root_span.update(output=full_response)
