from bot.data.track import Track

import asyncio

async def main():
    track = await Track.from_url("https://youtube.com/playlist?list=PL4qbAKRYbRhyylmxFzqjMkDDBpwbbwb9l")
    print(track)

asyncio.run(main())

