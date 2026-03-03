class DummyChannel:
    async def declare_exchange(self, *args, **kwargs):
        return object()

    async def declare_queue(self, *args, **kwargs):
        class Q:
            async def bind(self, *a, **k):
                return None

            async def unbind(self, *a, **k):
                return None

        return Q()

    async def close(self):
        return None


class DummyAMQP:
    async def channel(self):
        return DummyChannel()
