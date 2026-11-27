"""No more than AI_MAX_CONCURRENT_CALLS model calls are in flight at once, however many jobs ask."""
import asyncio

import httpx


def test_model_calls_are_capped(monkeypatch):
    from app.core.config import settings
    from app.integrations.ai import openai_compatible as oc

    monkeypatch.setattr(settings, "AI_MAX_CONCURRENT_CALLS", 2)
    state = {"now": 0, "peak": 0}

    async def handler(request):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.02)
        state["now"] -= 1
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "ok"}}]})

    async def run():
        oc._GATES.clear()
        provider = oc.OpenAICompatibleProvider(name="t", base_url="http://x", api_key="k", model="m",
                                               http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        results = await asyncio.gather(*(provider.generate("hi") for _ in range(8)))
        assert all(r.ok for r in results)

    asyncio.run(run())
    assert state["peak"] == 2
