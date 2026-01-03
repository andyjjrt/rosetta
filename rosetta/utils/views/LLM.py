import time

import discord
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

UPDATE_INTERVAL_SECONDS = 1
DISCORD_CHAR_LIMIT = 4000
SAFE_SPLIT_LIMIT = 3980


class LLMView(discord.ui.LayoutView):
    def __init__(self, model: str):
        super().__init__()
        self.last_update_time = time.time()
        self.start_time, self.first_token_time, self.end_time = time.time(), None, None

        self.response_messages = []
        self.current_message_content = ""
        self.full_response = ""
        self.model = model

        self.usage = None
        self.ttft, self.tps, self.completion_tokens = 0.0, 0.0, 0

        self.add_item(discord.ui.TextDisplay(f"🧠 Thinking with `{model}`..."))

    def find_best_split_position(self, text: str, max_len: int) -> int:
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

    async def update_view(self, message: discord.WebhookMessage):
        self.clear_items()
        container = discord.ui.Container()

        for response in self.response_messages:
            container.add_item(discord.ui.TextDisplay(response))

        if not self.end_time:
            current_message = self.current_message_content + " █"
            container.add_item(discord.ui.TextDisplay(current_message))
        else:
            container.add_item(
                discord.ui.TextDisplay(
                    f"-# {self.model} • {self.tps:.2f} tps • TTFT: {self.ttft:.2f}s • Tokens: {self.completion_tokens}"
                )
            )
        self.add_item(container)

        await message.edit(view=self)

    async def update_chunk(
        self, message: discord.WebhookMessage, chunk: ChatCompletionChunk
    ):
        content = chunk.choices[0].delta.content
        self.usage = chunk.usage

        if content:
            if self.first_token_time is None and content:
                self.first_token_time = time.time()
            self.current_message_content += content
            self.full_response += content
            if len(self.current_message_content) > SAFE_SPLIT_LIMIT:
                split_pos = self.find_best_split_position(
                    self.current_message_content, SAFE_SPLIT_LIMIT
                )
                text_to_send, carry_over_text = (
                    self.current_message_content[:split_pos],
                    self.current_message_content[split_pos:],
                )
                self.response_messages.append(text_to_send.strip())
                self.current_message_content = carry_over_text.lstrip()

            if time.time() - self.last_update_time >= UPDATE_INTERVAL_SECONDS:
                if self.current_message_content:
                    await self.update_view(message)
                    self.last_update_time = time.time()

    async def end_chunk(self, message: discord.WebhookMessage):
        self.end_time = time.time()
        self.response_messages.append(self.current_message_content)

        if self.usage:
            self.completion_tokens = self.usage.completion_tokens
        if self.start_time and self.first_token_time:
            self.ttft = self.first_token_time - self.start_time
        if self.first_token_time and self.end_time:
            generation_time = self.end_time - self.first_token_time
            if generation_time > 0 and self.completion_tokens > 1:
                self.tps = (self.completion_tokens - 1) / generation_time

        await self.update_view(message)
