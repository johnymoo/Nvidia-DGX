"""A small asynchronous cache used by the visible tests."""


class AsyncTTLCache:
    def __init__(self, ttl_seconds, *, clock=None):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._values = {}

    async def get_or_load(self, key, loader):
        if key in self._values:
            return self._values[key]
        value = await loader()
        self._values[key] = value
        return value

    def invalidate(self, key):
        self._values.pop(key, None)

    def clear(self):
        self._values.clear()
