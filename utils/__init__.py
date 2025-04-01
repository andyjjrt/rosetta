import re

def split_markdown(md_text: str, max_length: int = 2000):
    parts = []
    current_part = []
    current_length = 0
    open_codeblock = None  # Track open code blocks

    lines = md_text.split("\n")

    for line in lines:
        line_length = len(line) + 1  # Include newline character

        # Check if adding this line exceeds max_length
        if current_length + line_length > max_length:
            # If inside a code block, close it
            if open_codeblock:
                current_part.append("```")
                current_length += 3

            parts.append("\n".join(current_part))
            current_part = []
            current_length = 0

            # If we were inside a code block, start a new one
            if open_codeblock:
                current_part.append(f"```{open_codeblock}")
                current_length += len(open_codeblock) + 4

        # Detect code block opening/closing
        codeblock_match = re.match(r"^```(\w*)$", line)
        if codeblock_match:
            lang = codeblock_match.group(1)
            if open_codeblock:  # Closing block
                open_codeblock = None
            else:  # Opening block
                open_codeblock = lang

        # Add line to current part
        current_part.append(line)
        current_length += line_length

    # Add remaining content
    if current_part:
        parts.append("\n".join(current_part))

    return parts
