import base64
import io
import time

import discord


class ImageView(discord.ui.LayoutView):
    def __init__(
        self,
        model: str,
        prompt: str,
        size: str,
        num_inference_steps: int,
        true_cfg_scale: float,
        seed: int | None = None,
    ):
        super().__init__(timeout=300)
        self.model = model
        self.prompt = prompt
        self.size = size
        self.num_inference_steps = num_inference_steps
        self.true_cfg_scale = true_cfg_scale
        self.seed = seed
        self.image_file: discord.File | None = None
        self.error: str | None = None

        # Timing and token analysis
        self.start_time = time.time()
        self.end_time: float | None = None
        self.generation_time: float = 0.0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0

        # Initial loading state
        self.container = self.construct_loading_container()
        self.add_item(self.container)

    def construct_loading_container(self) -> discord.ui.Container:
        container = discord.ui.Container()
        container.add_item(discord.ui.TextDisplay(f"🎨 Generating image with `{self.model}`..."))
        container.add_item(
            discord.ui.TextDisplay(f"-# Prompt: {self.prompt[:100]}{'...' if len(self.prompt) > 100 else ''}")
        )
        return container

    def construct_result_container(self) -> discord.ui.Container:
        container = discord.ui.Container()

        if self.error:
            container.add_item(discord.ui.TextDisplay(f"❌ **Error:** {self.error}"))
            # Show timing even on error
            if self.end_time:
                container.add_item(
                    discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
                )
                container.add_item(
                    discord.ui.TextDisplay(f"-# Failed after {self.generation_time:.2f}s")
                )
        elif self.image_file:
            container.add_item(
                discord.ui.MediaGallery(
                    discord.components.MediaGalleryItem(media="attachment://generated_image.png")
                )
            )
            container.add_item(
                discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
            )
            container.add_item(discord.ui.TextDisplay(f"**Prompt:** {self.prompt}"))
            container.add_item(
                discord.ui.Separator(spacing=discord.enums.SeparatorSpacing.small)
            )
            
            # Model and generation parameters
            footer_text = f"-# {self.model} • {self.size} • Steps: {self.num_inference_steps} • CFG: {self.true_cfg_scale}"
            if self.seed is not None:
                footer_text += f" • Seed: {self.seed}"
            footer_text += f" • ⏱️ {self.generation_time:.2f}s"
            container.add_item(discord.ui.TextDisplay(footer_text))

        return container

    def set_image(self, image_b64: str):
        """Set the generated image from base64 data."""
        self.end_time = time.time()
        self.generation_time = self.end_time - self.start_time
        image_bytes = base64.b64decode(image_b64)
        self.image_file = discord.File(io.BytesIO(image_bytes), filename="generated_image.png")

    def set_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0):
        """Set token usage statistics from API response."""
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens

    def set_error(self, error: str):
        """Set an error message."""
        self.end_time = time.time()
        self.generation_time = self.end_time - self.start_time
        self.error = error

    async def update_result(self, message: discord.WebhookMessage):
        """Update the view with the final result."""
        self.clear_items()
        self.container = self.construct_result_container()
        self.add_item(self.container)

        if self.image_file:
            await message.edit(view=self, attachments=[self.image_file])
        else:
            await message.edit(view=self)
