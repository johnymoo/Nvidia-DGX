"""Map asynchronous work over values."""

import asyncio


async def bounded_map(function, items, *, limit):
    return await asyncio.gather(*(function(item) for item in items))
