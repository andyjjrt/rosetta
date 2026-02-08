import time

import discord
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

UPDATE_INTERVAL_SECONDS = 1
DISCORD_CHAR_LIMIT = 4000
SAFE_SPLIT_LIMIT = 3900
THINKING_DISPLAY_LIMIT = 500


class LLMView(discord.ui.LayoutView):
    def __init__(self, model: str, prompt: str = "", image_url: str | None = None):
        super().__init__(timeout=300)
        self.last_update_time = time.time()
        self.start_time, self.first_token_time, self.end_time = time.time(), None, None

        self.response_messages = []
        self.current_message_content = ""
        self.full_response = ""
        self.thinking_content = ""
        self.model = model
        self.prompt = prompt
        self.image_url = image_url
        self.current_page = 1
        self.message: discord.WebhookMessage | None = None
        self.cancelled = False

        self.usage = None
        self.ttft, self.tps, self.completion_tokens = 0.0, 0.0, 0

        # Initial loading state
        self.container = self.construct_loading_container()
        self.add_item(self.container)

    def construct_loading_container(self) -> discord.ui.Container:
        container = discord.ui.Container()
        
        # Show attached image at the top if present
        if self.image_url:
            container.add_item(
                discord.ui.MediaGallery(
                    discord.components.MediaGalleryItem(media=self.image_url)
                )
            )
        
        container.add_item(discord.ui.TextDisplay(f"🧠 Thinking with `{self.model}`..."))
        if self.prompt:
            truncated_prompt = self.prompt[:100] + ('...' if len(self.prompt) > 100 else '')
            container.add_item(
                discord.ui.TextDisplay(f"-# Prompt: {truncated_prompt}")
            )
        return container

    async def cancel_callback(self, interaction: discord.Interaction):
        self.cancelled = True
        await interaction.response.defer()

    def _format_thinking(self, show_cursor: bool = False) -> str:
        """Format thinking content as a blockquote."""
        text = self.thinking_content
        if not text:
            return ""

        if show_cursor:
            # Still actively thinking - show the tail
            if len(text) > THINKING_DISPLAY_LIMIT:
                text = "..." + text[-(THINKING_DISPLAY_LIMIT - 3):]
        else:
            # Thinking complete - show the beginning
            if len(text) > THINKING_DISPLAY_LIMIT:
                text = text[:THINKING_DISPLAY_LIMIT] + "..."

        lines = text.split('\n')
        quoted = '\n'.join(f'> {line}' for line in lines)
        if show_cursor:
            quoted += " █"
        return quoted

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

    def refresh_item(self, old_item: discord.ui.Item, new_item: discord.ui.Item):
        new_item._update_view(self)
        self._swap_item(old_item, new_item, "")
        del old_item

    def pagination_callback(self, current_page: int = 1):
        async def _callback(interaction: discord.Interaction):
            total_pages = len(self.response_messages)
            new_page = current_page

            if interaction.data["custom_id"] == "next":
                new_page = min(current_page + 1, total_pages)
            elif interaction.data["custom_id"] == "previous":
                new_page = max(current_page - 1, 1)

            self.current_page = new_page
            new_container = self.construct_container(new_page)
            self.refresh_item(self.container, new_container)
            self.container = new_container

            await interaction.response.edit_message(view=self)

        return _callback

    def construct_container(self, page: int = -1):
        container = discord.ui.Container()
        total_pages = len(self.response_messages)

        # Show attached image at the top if present
        if self.image_url:
            container.add_item(
                discord.ui.MediaGallery(
                    discord.components.MediaGalleryItem(media=self.image_url)
                )
            )

        # page -1 means show current streaming content only
        if page == -1:
            # Show thinking content in blockquote if available
            if self.thinking_content:
                is_still_thinking = not bool(self.current_message_content)
                container.add_item(
                    discord.ui.TextDisplay(self._format_thinking(show_cursor=is_still_thinking))
                )

            if self.current_message_content:
                current_message = self.current_message_content + " █"
                container.add_item(discord.ui.TextDisplay(current_message))
            # Add cancel button during streaming
            cancel_row = discord.ui.ActionRow()
            cancel_button = discord.ui.Button(
                label="Cancel", style=discord.ButtonStyle.danger, custom_id="cancel"
            )
            cancel_button.callback = self.cancel_callback
            cancel_row.add_item(cancel_button)
            container.add_item(cancel_row)
        elif total_pages > 0 and 1 <= page <= total_pages:
            # Show thinking on the first page
            if self.thinking_content and page == 1:
                container.add_item(
                    discord.ui.TextDisplay(self._format_thinking(show_cursor=False))
                )
            # Show only the specified page's content (1 response message per page)
            page_content = self.response_messages[page - 1]
            container.add_item(discord.ui.TextDisplay(page_content))

        # Footer with stats (only when finished)
        if self.end_time:
            container.add_item(
                discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
            )
            status = "Cancelled" if self.cancelled else f"{self.tps:.2f} tps"
            container.add_item(
                discord.ui.TextDisplay(
                    f"-# {self.model} • {status} • TTFT: {self.ttft:.2f}s • Tokens: {self.completion_tokens}"
                )
            )

        # Pagination controls (only when there are multiple pages and streaming is done)
        if self.end_time and total_pages > 1:
            container.add_item(
                discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
            )
            footer = discord.ui.TextDisplay(f"-# Page {self.current_page}/{total_pages}")
            container.add_item(footer)

            actionrow = discord.ui.ActionRow()
            previous_button = discord.ui.Button(
                label="Previous", custom_id="previous", disabled=self.current_page <= 1
            )
            previous_button.callback = self.pagination_callback(self.current_page)
            actionrow.add_item(previous_button)

            next_button = discord.ui.Button(
                label="Next", custom_id="next", disabled=self.current_page >= total_pages
            )
            next_button.callback = self.pagination_callback(self.current_page)
            actionrow.add_item(next_button)

            container.add_item(actionrow)

        return container

    async def update_view(self, message: discord.WebhookMessage, page: int = -1):
        self.message = message
        self.clear_items()
        self.container = self.construct_container(page)
        self.add_item(self.container)

        await message.edit(view=self, allowed_mentions=discord.AllowedMentions.none())

    async def update_chunk(
        self, message: discord.WebhookMessage, chunk: ChatCompletionChunk
    ):
        if not chunk.choices:
            self.usage = chunk.usage
            return

        delta = chunk.choices[0].delta
        content = delta.content
        reasoning = getattr(delta, 'reasoning_content', None)
        self.usage = chunk.usage

        needs_update = False

        if reasoning:
            if self.first_token_time is None:
                self.first_token_time = time.time()
            self.thinking_content += reasoning
            needs_update = True

        if content:
            if self.first_token_time is None:
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
            needs_update = True

        if needs_update and time.time() - self.last_update_time >= UPDATE_INTERVAL_SECONDS:
            await self.update_view(message)
            self.last_update_time = time.time()

    async def end_chunk(self, message: discord.WebhookMessage):
        self.end_time = time.time()
        self.response_messages.append(self.current_message_content)
        self.current_page = len(self.response_messages)  # Go to the last page

        if self.usage:
            self.completion_tokens = self.usage.completion_tokens
        if self.start_time and self.first_token_time:
            self.ttft = self.first_token_time - self.start_time
        if self.first_token_time and self.end_time:
            generation_time = self.end_time - self.first_token_time
            if generation_time > 0 and self.completion_tokens > 1:
                self.tps = (self.completion_tokens - 1) / generation_time

        await self.update_view(message, self.current_page)
